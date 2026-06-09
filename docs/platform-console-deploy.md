# WAIIS Console (in-Platform) — deploy
- The console + brain live in the Django fork; mounted at /console/*, login-gated.
- Env on the waiis-dispatch-platform Railway services:
  - AGENT_SERVICE_BASE_URL=https://web-production-e7cf9.up.railway.app
  - AGENT_SERVICE_TOKEN=<JWT for a dedicated 'platform' agent-service user>
- Mint the token: create a 'platform' user in agent-service (role lead) and POST /auth/login to get
  its JWT (long TTL); set it as AGENT_SERVICE_TOKEN. Rotate via re-login.
- agent-service /graph is already deployed. Deploy the fork (railway up), open /console/ -> sign in
  (Platform login) -> Ideas/Drafts/AI Approvals/Pipeline/Brain render live agent-service data.
