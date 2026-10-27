// Where the Hearten API lives: the local dev server while developing, and the
// deployed API (the api_url output of `terraform apply` in infra/) otherwise.
const DEPLOYED_API = "https://ivbjtoah4f.execute-api.us-west-2.amazonaws.com/";

window.HEARTEN_API = ["localhost", "127.0.0.1"].includes(location.hostname)
  ? "http://127.0.0.1:8000"
  : DEPLOYED_API.replace(/\/$/, "");
