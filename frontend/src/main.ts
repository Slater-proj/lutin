import { mount } from "svelte";
import App from "./App.svelte";
import { applyTheme, readTheme } from "./lib/theme";
import "./styles/tokens.css";
import "./styles/base.css";

applyTheme(readTheme()); // before the first paint of the application: no flash of the other theme

const target = document.getElementById("app");
if (target) {
  mount(App, { target });
}
