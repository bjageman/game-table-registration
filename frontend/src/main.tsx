import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "material/styles/base";
import "./style.css";
document.documentElement.dataset.theme = "baseline";
document.documentElement.dataset.themeMode = "light";
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
