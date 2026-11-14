"""Auth API routes."""

import re
import secrets
import time
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import delete
from sqlalchemy.orm import Session as DBSession

from app.context import ApplicationContext
from app.events.test_signups import (
    allowed as test_users_allowed,
)
from app.models import (
    AssignmentPreference,
    LoginState,
    Organization,
    OrganizationMember,
    Session,
    UserIdentity,
    UserSettings,
)
from app.security import digest
from app.settings.assignment_preferences import scope_key as assignment_scope_key
from app.settings.connection_settings import (
    POLL_PERMISSIONS,
    SIGNUP_PERMISSIONS,
)
from app.settings.organization_selection import selected_organization


def register(context: ApplicationContext) -> None:
    router = APIRouter()
    app = context.app
    authenticated = context.authenticated
    config = context.config
    cookie = context.cookie
    engine = context.engine
    legacy_access = context.legacy_access

    def begin_login(return_to: str = "", user_id: str | None = None) -> Response:
        if not config.configured:
            raise HTTPException(
                503, "Complete Discord configuration before signing in."
            )
        token = secrets.token_urlsafe(32)
        with DBSession(engine) as db:
            db.execute(delete(LoginState).where(LoginState.expires < time.time()))
            db.execute(delete(Session).where(Session.expires < time.time()))
            db.add(
                LoginState(
                    token_hash=digest(token),
                    expires=time.time() + 600,
                    purpose="connect" if user_id else "login",
                    user_id=user_id,
                )
            )
            db.commit()
        params = {
            "client_id": config.discord_client_id,
            "response_type": "code",
            "scope": "identify guilds bot" if user_id else "identify guilds",
            "redirect_uri": config.callback_url,
            "state": token,
        }
        if user_id:
            params.update(
                permissions=str(
                    (
                        POLL_PERMISSIONS
                        if config.discord_signup_mode == "poll"
                        else SIGNUP_PERMISSIONS
                    )
                    | (1 << 44)
                ),
                integration_type="0",
                prompt="consent",
            )
        response = RedirectResponse(
            "https://discord.com/oauth2/authorize?" + urlencode(params)
        )
        cookie(response, "oauth_state", token, 600)
        cookie(
            response, "oauth_return", "settings" if return_to == "settings" else "", 600
        )
        return response

    @router.get("/api/auth/login")
    def login(return_to: str = "") -> Response:
        return begin_login(return_to)

    @router.get("/api/auth/connect")
    def connect(request: Request) -> Response:
        session = authenticated(request, require_destination=False)
        if request.state.organization_id and request.state.organization_role != "admin":
            raise HTTPException(403, "Organization admin access required")
        response = begin_login("settings", session.user_id)
        cookie(response, "oauth_organization", request.state.organization_id or "", 600)
        return response

    @router.get("/api/auth/callback")
    def callback(
        request: Request, code: str = "", state: str = "", guild_id: str = ""
    ) -> Response:
        if not state or not secrets.compare_digest(
            state, request.cookies.get("oauth_state", "")
        ):
            raise HTTPException(400, "Invalid login state. Start sign-in again.")
        with DBSession(engine) as db:
            consumed = db.execute(
                delete(LoginState)
                .where(
                    LoginState.token_hash == digest(state),
                    LoginState.expires > time.time(),
                )
                .returning(LoginState.purpose, LoginState.user_id)
            ).first()
            db.commit()
            if not consumed or not code:
                raise HTTPException(400, "Login expired or cancelled. Sign in again.")
            if consumed.purpose == "connect":
                current = authenticated(request, require_destination=False)
                if current.user_id != consumed.user_id:
                    raise HTTPException(
                        403,
                        "Connection was started by another account. "
                        "Start Connect again.",
                    )
            user = app.state.discord.identity(code)
            if consumed.purpose == "connect":
                if user["id"] != consumed.user_id:
                    raise HTTPException(
                        403, "Authorize with the Discord account you signed in with."
                    )
                authorized = user.get("authorized_guild") or {}
                chosen_id = str(authorized.get("id") or guild_id)
                if not re.fullmatch(r"[0-9]{1,32}", chosen_id):
                    raise HTTPException(
                        400,
                        "Discord did not return the authorized server. "
                        "Start Connect again.",
                    )
                if authorized.get("id") and guild_id and chosen_id != guild_id:
                    raise HTTPException(
                        400, "Discord server did not match the authorization."
                    )
                # guild_id is only a hint; verify manager and bot access.
                guild, _, _ = app.state.discord.manager_context(user["id"], chosen_id)
                if str(guild.get("id")) != chosen_id:
                    raise HTTPException(502, "Could not verify the authorized server.")
                organization_id = request.cookies.get("oauth_organization", "")
                if organization_id:
                    organization = db.get(Organization, organization_id)
                    member = db.get(OrganizationMember, (organization_id, user["id"]))
                    if not organization or not member or member.role != "admin":
                        raise HTTPException(403, "Organization admin access required")
                    if organization.guild_id != chosen_id:
                        organization.channel_id = ""
                    organization.guild_id = chosen_id
                else:
                    previous = db.get(UserSettings, user["id"])
                    keep_channel = (
                        previous is not None
                        and not previous.disconnected
                        and previous.guild_id == chosen_id
                    )
                    db.merge(
                        UserSettings(
                            user_id=user["id"],
                            disconnected=False,
                            guild_id=chosen_id,
                            guild_name=str(guild["name"]),
                            channel_id=previous.channel_id
                            if keep_channel and previous
                            else "",
                            channel_name=previous.channel_name
                            if keep_channel and previous
                            else "",
                        )
                    )
            token = secrets.token_urlsafe(32)
            db.execute(
                delete(Session).where(
                    Session.token_hash == digest(request.cookies.get("session", ""))
                )
            )
            db.add(
                Session(
                    token_hash=digest(token),
                    user_id=user["id"],
                    username=user["username"],
                    guilds=[
                        {"id": str(g["id"]), "name": str(g["name"])}
                        for g in user.get("guilds", [])
                        if g.get("owner") or int(g.get("permissions", "0")) & (8 | 32)
                    ],
                    csrf=secrets.token_urlsafe(32),
                    expires=time.time() + 28800,
                )
            )
            db.merge(UserIdentity(id=user["id"], username=user["username"]))
            db.commit()
        response = RedirectResponse(
            config.public_url + "/#/settings"
            if consumed.purpose == "connect"
            or request.cookies.get("oauth_return") == "settings"
            else config.public_url
        )
        response.delete_cookie("oauth_state", path="/api")
        response.delete_cookie("oauth_return", path="/api")
        response.delete_cookie("oauth_organization", path="/api")
        cookie(response, "session", token, 28800)
        return response

    @router.get("/api/me")
    def me(request: Request) -> dict[str, Any]:
        session = authenticated(request, require_destination=False)
        with DBSession(engine) as db:
            db.merge(UserIdentity(id=session.user_id, username=session.username))
            db.commit()
            saved = db.get(UserSettings, session.user_id)
            organization, membership = selected_organization(db, session.user_id)
            selection = (
                (
                    "disconnected"
                    if saved.disconnected
                    else f"{saved.guild_id}:{saved.channel_id}"
                )
                if saved
                else "legacy"
            )
            preferences = db.get(
                AssignmentPreference,
                assignment_scope_key(
                    organization.id if organization else None, session.user_id
                ),
            )
            timezone = preferences.timezone if preferences else None
        needs_setup = (
            not bool(organization.channel_id)
            if organization
            else (
                (saved.disconnected or not saved.channel_id)
                if saved
                else not legacy_access(session.user_id)
            )
        )
        return {
            "username": session.username,
            "user_id": session.user_id,
            "csrf": session.csrf,
            "needs_setup": needs_setup,
            "destination": selection,
            "timezone": timezone,
            "organization": {"id": organization.id, "name": organization.name}
            if organization
            else None,
            "organization_role": membership.role
            if organization and membership
            else None,
            "can_populate_test_users": test_users_allowed(session.user_id, config),
        }

    @router.post("/api/auth/logout")
    def logout(request: Request) -> Response:
        session = authenticated(request, True, require_destination=False)
        with DBSession(engine) as db:
            db.execute(delete(Session).where(Session.token_hash == session.token_hash))
            db.commit()
        response = Response(status_code=204)
        response.delete_cookie("session", path="/api")
        return response

    context.app.include_router(router)
