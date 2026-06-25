import typer
import uvicorn
import textwrap
import httpx
import asyncio
import json
import webbrowser
from rich.console import Console
from rich.table import Table
from rich import print as rprint
import db

app = typer.Typer(
    help="DebateItOut — multi-model AI debate orchestrator",
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]}
)

console = Console()

# We can group subcommands
debates_app = typer.Typer(help="Manage debates")
endpoints_app = typer.Typer(help="Manage API endpoints")
models_app = typer.Typer(help="Fetch available models")

app.add_typer(debates_app, name="debates", help="Manage active and past debates")
app.add_typer(endpoints_app, name="endpoints", help="Manage API endpoints (OpenAI, Anthropic)")
app.add_typer(models_app, name="models", help="Dynamically fetch models from endpoints")

@app.command()
def start(port: int = 3002):
    """
    Launch the debate engine (foreground).
    """
    msg = f"""
    🌌 Launching DebateItOut...
    ╭────────────────────────────────────────────────╮
    │ ⚡ Debate engine is now in orbit!              │
    ╰────────────────────────────────────────────────╯

       ┌─ Local UI: http://localhost:{port}
       └─ API Base: http://localhost:{port}/api/
       
       Next steps:
       • Open the UI in your browser to configure endpoints.
       • Press Ctrl+C to shut down.
    """
    console.print(textwrap.dedent(msg), style="bold blue")
    
    uvicorn.run("main:app", host="127.0.0.1", port=port, log_level="warning")

@app.command()
def ui(port: int = 3002):
    """
    Open the WebUI in your default browser.
    """
    url = f"http://localhost:{port}"
    console.print(f"Opening WebUI at [bold cyan]{url}[/bold cyan]...")
    webbrowser.open(url)

@app.command()
def status(port: int = 3002):
    """
    Check if the engine is running.
    """
    try:
        r = httpx.get(f"http://127.0.0.1:{port}/api/config", timeout=2.0)
        if r.status_code == 200:
            console.print("[bold green]DebateItOut is running![/bold green]")
            console.print(f"Port: {port}")
            console.print(f"Auto-advance: {r.json().get('autoAdvance', False)}")
        else:
            console.print(f"[bold yellow]Server returned status {r.status_code}[/bold yellow]")
    except httpx.RequestError:
        console.print("[bold red]DebateItOut is not running.[/bold red]")

# --- DEBATES ---

@debates_app.command("list")
def list_debates():
    """List all active and past debates."""
    async def _list():
        await db.init_pool()
        d_list = await db.get_all_debates()
        await db.close_pool()
        return d_list

    d_list = asyncio.run(_list())
    if not d_list:
        console.print("No debates found.")
        return

    table = Table("ID", "Name/Proposition", "Rounds", "Status")
    for d in d_list:
        name = d.get("customName") or d.get("propositionPreview", "")[:30] + "..."
        rounds = f"{d['currentRound']} / {d['maxRounds']}"
        table.add_row(d["id"][:8], name, rounds, d["status"])
    
    console.print(table)

@debates_app.command("rm")
def rm_debate(debate_id: str):
    """Delete a debate by ID."""
    async def _rm():
        await db.init_pool()
        res = await db.delete_debate(debate_id)
        await db.close_pool()
        return res
    
    res = asyncio.run(_rm())
    if res:
        console.print(f"[green]Deleted debate {debate_id}[/green]")
    else:
        console.print(f"[red]Debate not found or failed to delete[/red]")

@debates_app.command("export")
def export_debate(debate_id: str, format: str = typer.Option(None, help="json or md")):
    """Export a debate transcript."""
    if format not in [None, "json", "md"]:
        console.print("[red]Format must be json or md[/red]")
        raise typer.Exit(1)
        
    if format is None:
        format = typer.prompt("Export format? [json/md]")

    async def _get():
        await db.init_pool()
        d = await db.get_debate(debate_id)
        if not d:
            await db.close_pool()
            return None, None
        msgs = await db.get_messages(debate_id)
        await db.close_pool()
        return d, msgs
        
    d, msgs = asyncio.run(_get())
    if not d:
        console.print(f"[red]Debate {debate_id} not found[/red]")
        raise typer.Exit(1)

    filename = f"debate_{debate_id[:8]}.{format}"
    
    if format == "json":
        data = {"debate": d, "messages": msgs}
        with open(filename, "w") as f:
            json.dump(data, f, indent=2)
    else:
        with open(filename, "w") as f:
            f.write(f"# Debate: {d.get('proposition')}\n\n")
            for m in msgs:
                f.write(f"### {m['faction']} - {m['modelId'].split('|')[-1]} (Round {m['round']})\n")
                if m.get('teamMsg'):
                    f.write(f"**Team Message:**\n{m['teamMsg']}\n\n")
                if m.get('argument'):
                    f.write(f"**Argument:**\n{m['argument']}\n\n")
                f.write("---\n")
                
    console.print(f"[green]Exported to {filename}[/green]")

# --- ENDPOINTS ---

@endpoints_app.command("list")
def list_endpoints():
    """List all connected API endpoints."""
    async def _list():
        await db.init_pool()
        ep = await db.get_all_endpoints()
        await db.close_pool()
        return ep
        
    ep_list = asyncio.run(_list())
    if not ep_list:
        console.print("No endpoints configured.")
        return
        
    table = Table("ID", "Name", "Type", "Base URL")
    for ep in ep_list:
        table.add_row(ep["id"][:8], ep["name"], ep["type"], ep["baseUrl"])
    
    console.print(table)

@endpoints_app.command("add")
def add_endpoint():
    """Interactively add an OpenAI/Anthropic endpoint."""
    name = typer.prompt("Endpoint name (e.g. Local Ollama, OpenRouter)")
    ep_type = typer.prompt("Type [openai/anthropic]")
    base_url = typer.prompt("Base URL")
    api_key = typer.prompt("API Key", hide_input=True)
    
    async def _add():
        await db.init_pool()
        ep = await db.create_endpoint(name, ep_type, base_url, api_key)
        await db.close_pool()
        return ep
        
    ep = asyncio.run(_add())
    console.print(f"[green]Added endpoint {ep['id'][:8]} - {ep['name']}[/green]")


# --- MODELS ---

@models_app.command("list")
def list_models(endpoint_id: str = typer.Argument(None, help="Optional endpoint ID prefix to filter")):
    """Fetch and list available models from endpoints."""
    # Since models dynamically fetch via API, we hit the local server if running, 
    # but the instructions requested we can do it via DB too. Hitting DB logic directly is better since we may not have the server running.
    
    async def _fetch():
        await db.init_pool()
        endpoints = await db.get_all_endpoints()
        await db.close_pool()
        
        all_models = []
        for ep in endpoints:
            if endpoint_id and not ep["id"].startswith(endpoint_id):
                continue
            
            try:
                base_url = ep["baseUrl"].rstrip("/")
                if ep["type"] == "anthropic":
                    all_models.extend([
                        {"id": f"{ep['id']}|claude-3-5-sonnet-20240620", "name": "claude-3-5-sonnet", "endpoint": ep["name"]},
                        {"id": f"{ep['id']}|claude-3-haiku-20240307", "name": "claude-3-haiku", "endpoint": ep["name"]}
                    ])
                else:
                    url = f"{base_url}/models" if not base_url.endswith("/v1") else f"{base_url}/models"
                    if not url.endswith("/models"):
                        url = f"{base_url}/v1/models"
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        headers = {"Authorization": f"Bearer {ep['apiKey']}"}
                        resp = await client.get(url, headers=headers)
                        if resp.status_code == 200:
                            data = resp.json()
                            data_models = data.get("data", [])
                            for m in data_models:
                                slug = m["id"]
                                all_models.append({"id": f"{ep['id']}|{slug}", "name": slug, "endpoint": ep["name"]})
            except Exception as e:
                console.print(f"[yellow]Failed to fetch from {ep['name']}: {e}[/yellow]")
        return all_models

    with console.status("Fetching models..."):
        m_list = asyncio.run(_fetch())
        
    if not m_list:
        console.print("No models found.")
        return
        
    table = Table("Model Name", "Endpoint", "Full ID")
    for m in m_list:
        table.add_row(m["name"], m["endpoint"], m["id"])
    
    console.print(table)


if __name__ == "__main__":
    app()
