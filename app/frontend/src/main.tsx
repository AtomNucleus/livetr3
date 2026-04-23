import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import ProjectorApp from "./ProjectorApp";
import "./styles.css";

const RootComponent = window.location.pathname === "/projector" ? ProjectorApp : App;

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RootComponent />
  </React.StrictMode>,
);
