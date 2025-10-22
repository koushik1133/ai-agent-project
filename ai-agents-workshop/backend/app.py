from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from agents.root_agent import root_agent

app = FastAPI()

# Allow CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/agent")
async def agent_endpoint(request: Request):
    data = await request.json()
    prompt = data.get("prompt", "")
    result = root_agent(prompt)
    return result