import React from "react";
import ReactDOM from "react-dom/client";
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider";
import { AdapterDayjs } from "@mui/x-date-pickers/AdapterDayjs";
import App from "./app/App";
import PublicEvent from "./features/events/sharing/PublicEvent";
import "./styles/style.css";
function Root() {
  const [hash, setHash] = React.useState(window.location.hash);
  React.useEffect(() => {
    const changed = () => setHash(window.location.hash);
    window.addEventListener("hashchange", changed);
    return () => window.removeEventListener("hashchange", changed);
  }, []);
  const shared = /^#\/shared\/([A-Za-z0-9_-]+)$/.exec(hash);
  return shared ? <PublicEvent key={shared[1]} token={shared[1]} /> : <App />;
}
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <LocalizationProvider dateAdapter={AdapterDayjs}>
      <Root />
    </LocalizationProvider>
  </React.StrictMode>,
);
