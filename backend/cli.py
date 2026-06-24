import typer
import uvicorn
import textwrap

app = typer.Typer(help="DebateItOut CLI")

@app.command()
def start(port: int = 3002):
    """
    Start the DebateItOut local server.
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
    typer.echo(textwrap.dedent(msg))
    
    # Run uvicorn programmatically
    # We use "main:app" assuming this is run in an environment where main is importable
    uvicorn.run("main:app", host="127.0.0.1", port=port, log_level="warning")

if __name__ == "__main__":
    app()
