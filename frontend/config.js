// Where the Hearten API lives. Local development uses the uvicorn dev server;
// the deployed address is filled in when the API is deployed (build step 8).
window.HEARTEN_API = ["localhost", "127.0.0.1"].includes(location.hostname)
  ? "http://127.0.0.1:8000"
  : "";
