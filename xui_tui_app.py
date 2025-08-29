#!/usr/bin/env python3
import requests
import json
import os
import getpass
import uuid
import sys
from urllib.parse import urlparse, urljoin

from rich.console import Console
from rich.prompt import Prompt
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.panel import Panel

# Global console for rich output
console = Console()

# --- Configuration Handling ---
CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".xui_tui_config.json")  # Store config in user's home directory

def load_config():
    """Loads X-UI panel configuration from a JSON file."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            console.print(f"[bold red]Error: Could not parse {CONFIG_FILE}. It might be corrupted.[/bold red]")
            return None
    return None

def save_config(config):
    """Saves X-UI panel configuration to a JSON file."""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
        console.print(f"[bold green]Configuration saved to {CONFIG_FILE}[/bold green]")
    except IOError as e:
        console.print(f"[bold red]Error: Could not save configuration to {CONFIG_FILE}: {e}[/bold red]")

# --- X-UI API Client ---
class XUIAPI:
    """A client for interacting with the X-UI panel API."""
    def __init__(self, base_url, username, password, verify_ssl=True):
        self.base_url = base_url.rstrip('/') + '/'  # Ensure trailing slash for urljoin
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.verify_ssl = verify_ssl

        parsed_url = urlparse(self.base_url)
        host_header = parsed_url.netloc

        self.session.headers.update({
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Host': host_header,
        })
        self.login_status = False

    def _request(self, method, endpoint, json_data=None, data=None):
        """
        Helper to make API requests and handle errors. Uses session for cookie persistence.
        """
        url = urljoin(self.base_url, endpoint)
        original_content_type = self.session.headers.get('Content-Type')

        try:
            if method == "POST":
                if json_data is not None:
                    self.session.headers.update({'Content-Type': 'application/json'})
                    resp = self.session.post(url, json=json_data, timeout=15, verify=self.verify_ssl)
                else:
                    self.session.headers.update({'Content-Type': 'application/x-www-form-urlencoded'})
                    resp = self.session.post(url, data=data, timeout=15, verify=self.verify_ssl)
            elif method == "GET":
                resp = self.session.get(url, timeout=15, verify=self.verify_ssl)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
        except requests.exceptions.SSLError as e:
            console.print(f"[bold red]SSL/TLS Error for {url}: {e}[/bold red]")
            return None
        except requests.exceptions.ConnectionError as e:
            console.print(f"[bold red]Connection Error for {url}: {e}[/bold red]")
            return None
        except requests.exceptions.Timeout:
            console.print(f"[bold red]Request timed out for {url}[/bold red]")
            return None
        finally:
            # Restore header no matter what
            self.session.headers.update({'Content-Type': original_content_type})

        # HTTP-level errors
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            body = resp.text
            console.print(f"[bold red]HTTP Error for {url}: {e.response.status_code} - {body}[/bold red]")
            return None

        # Parse JSON and X-UI success flag
        try:
            res_json = resp.json()
        except json.JSONDecodeError:
            console.print(f"[bold red]Non-JSON response from {url}: {resp.text[:300]}[/bold red]")
            return None

        if not res_json.get('success', False):
            # Show server-provided message if any
            msg = res_json.get('msg', 'Unknown X-UI API error.')
            console.print(f"[bold red]X-UI API Error: {msg}[/bold red]")
            return None

        return res_json

    def login(self):
        """Authenticates and stores session cookie."""
        console.print("[bold blue]Logging in to X-UI...[/bold blue]")
        data = {"username": self.username, "password": self.password}
        res = self._request("POST", "login", data=data)
        if res and res.get('success'):
            self.login_status = True
            console.print("[bold green]Login successful![/bold green]")
            return True
        self.login_status = False
        console.print("[bold red]Login failed. Check URL/credentials.[/bold red]")
        return False

    def get_inbounds(self):
        if not self.login_status:
            console.print("[bold red]Not logged in. Please log in first.[/bold red]")
            return None
        return self._request("GET", "panel/api/inbounds/list")

    def get_inbound_details(self, inbound_id):
        if not self.login_status:
            console.print("[bold red]Not logged in. Please log in first.[/bold red]")
            return None
        res = self.get_inbounds()
        if res and res.get('obj'):
            for inbound in res['obj']:
                if inbound['id'] == inbound_id:
                    return inbound
        return None

    def update_inbound(self, inbound_config: dict):
        """Updates an inbound using the documented id+settings (string) payload."""
        if not self.login_status:
            console.print("[bold red]Not logged in. Please log in first.[/bold red]")
            return None

        settings = inbound_config.get('settings')
        settings_str = json.dumps(settings) if isinstance(settings, dict) else settings
        payload = {"id": inbound_config["id"], "settings": settings_str}
        return self._request("POST", "panel/api/inbounds/update", data=payload)

    def add_client(self, inbound_id: int, client_label: str, client_secret: str = None, **kwargs):
        """
        Add a client to an inbound using the documented addClient format:
        payload = {"id": <inbound_id>, "settings": "{\"clients\":[{...}]}"}

        - For VLESS: sends only "id" (UUID) — no password field.
        - For VMess: sends "id" (UUID). alterId defaults to 0.
        - For Trojan: sends "password" only.

        NOTE: To avoid X-UI auto-generating labels and causing duplicate errors, we
        send a payload with ONLY the new client in settings, not the full list.
        """
        if not self.login_status:
            console.print("[bold red]Not logged in. Please log in first.[/bold red]")
            return False

        inbound = self.get_inbound_details(inbound_id)
        if not inbound:
            console.print(f"[bold red]Inbound {inbound_id} not found.[/bold red]")
            return False

        protocol = inbound['protocol'].lower()

        # Pre-check: avoid duplicate labels (email field used as label)
        try:
            current = json.loads(inbound['settings'])
            existing_labels = {c.get('email') for c in current.get('clients', [])}
            if client_label in existing_labels:
                console.print(f"[bold yellow]Client label '{client_label}' already exists in inbound {inbound_id}. Skipping.[/bold yellow]")
                return False
        except Exception:
            pass

        # Build new client object according to protocol
        new_uuid = str(uuid.uuid4())
        secret = client_secret if client_secret else str(uuid.uuid4())

        client_obj = {
            "email": client_label,
            "enable": True,
            "flow": kwargs.get("flow", ""),
            "limitIp": kwargs.get("limitIp", 0),
            "totalGB": kwargs.get("totalGB", 0),
            "expiryTime": kwargs.get("expiryTime", 0),
            "tgId": kwargs.get("tgId", ""),
            "subId": kwargs.get("subId", str(uuid.uuid4())[:12]),
            "reset": 0,
        }

        if protocol == 'vless':
            client_obj['id'] = new_uuid  # UUID
            # Do NOT include password for VLESS
        elif protocol == 'vmess':
            client_obj['id'] = new_uuid if client_secret is None else client_secret
            client_obj['alterId'] = kwargs.get('alterId', 0)
        elif protocol == 'trojan':
            client_obj['password'] = secret
        else:
            console.print(f"[bold red]Protocol '{protocol}' not supported for addClient in this tool.[/bold red]")
            return False

        # 🔑 Critical: send ONLY the new client in settings
        payload = {
            "id": inbound_id,
            "settings": json.dumps({"clients": [client_obj]})
        }

        res = self._request("POST", "panel/api/inbounds/addClient", data=payload)
        if res and res.get('success'):
            console.print(f"[bold green]Client '{client_label}' added to inbound {inbound_id}.[/bold green]")
            return True
        return False

# --- Helper Functions for TUI Menu Logic ---
def get_inbound_selection(xui_api):
    """Fetches, displays, and prompts for inbound selection."""
    console.print("\n[bold blue]Fetching inbounds...[/bold blue]")
    inbounds_res = xui_api.get_inbounds()

    if not inbounds_res or not isinstance(inbounds_res, dict) or not inbounds_res.get('obj'):
        console.print("[bold yellow]No inbounds found or error fetching inbounds, or invalid response format.[/bold yellow]")
        return None

    inbounds = inbounds_res['obj']

    inbound_table = Table(title="Available Inbounds", show_lines=True)
    inbound_table.add_column("Index", style="cyan", justify="center")
    inbound_table.add_column("ID", style="magenta")
    inbound_table.add_column("Name", style="green")
    inbound_table.add_column("Protocol", style="yellow")
    inbound_table.add_column("Port", style="blue")

    for i, inbound in enumerate(inbounds):
        inbound_table.add_row(
            str(i + 1),
            str(inbound['id']),
            inbound.get('remark', ''),
            inbound['protocol'].upper(),
            str(inbound['port'])
        )

    console.print(inbound_table)

    selected_indices_str = Prompt.ask(
        "\n[bold white]Enter comma-separated indices of inbounds to manage[/bold white] (e.g., 1,3,4 or 'all')",
        default="all"
    )

    selected_inbound_ids = []
    if selected_indices_str.lower() == "all":
        selected_inbound_ids = [inb['id'] for inb in inbounds]
    else:
        try:
            indices = [int(x.strip()) for x in selected_indices_str.split(',') if x.strip()]
            for idx in indices:
                if 1 <= idx <= len(inbounds):
                    selected_inbound_ids.append(inbounds[idx - 1]['id'])
                else:
                    console.print(f"[bold yellow]Warning: Index {idx} is out of range. Skipping.[/bold yellow]")
        except ValueError:
            console.print("[bold red]Invalid input for inbound selection. Returning to main menu.[/bold red]")
            return None

    if not selected_inbound_ids:
        console.print("[bold yellow]No inbounds selected. Returning to main menu.[/bold yellow]")
        return None

    return selected_inbound_ids, inbounds


def display_summary_table(results, title):
    """Displays a formatted summary table of client operations."""
    console.print(Panel(f"[bold white]{title}[/bold white]", expand=False))
    summary_table = Table(title=title, show_lines=True)
    summary_table.add_column("Inbound", style="cyan")
    summary_table.add_column("Status", style="magenta")
    summary_table.add_column("Action", style="green")
    summary_table.add_column("Message", style="blue")

    for res in results:
        status_style = "green" if res['status'] == "Success" else "red"
        summary_table.add_row(res['inbound'], f"[{status_style}]{res['status']}[/{status_style}]", res['action'], res['message'])
    console.print(summary_table)
    console.print("\n[bold green]Operation complete![/bold green]")


def handle_add_client(xui_api):
    """Handles the 'Add Client' menu option."""
    selection_result = get_inbound_selection(xui_api)
    if selection_result is None:
        return

    selected_inbound_ids, all_inbounds = selection_result

    client_label = Prompt.ask("Enter label (email field) for the new client (e.g., user01 or user@example.com)")
    if not client_label:
        console.print("[bold red]Client label cannot be empty. Returning to main menu.[/bold red]")
        return

    client_secret = Prompt.ask("Enter secret (Trojan password / VMess id). Leave blank for auto.", default="")

    console.print(f"\n[bold white]Adding client '{client_label}' to {len(selected_inbound_ids)} inbound(s)...[/bold white]")

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), "{task.completed}/{task.total}", TextColumn("[progress.percentage]{task.percentage:>3.0f}%"), console=console, transient=True) as progress:
        add_task = progress.add_task("[cyan]Processing inbounds...", total=len(selected_inbound_ids))

        results = []
        for inbound_id in selected_inbound_ids:
            inbound_name = next((inb.get('remark', f"ID {inbound_id}") for inb in all_inbounds if inb['id'] == inbound_id), f"ID {inbound_id}")
            progress.update(add_task, description=f"[cyan]Adding to '{inbound_name}'...[/cyan]")
            try:
                ok = xui_api.add_client(inbound_id, client_label, client_secret or None)
                if ok:
                    results.append({"inbound": inbound_name, "status": "Success", "action": "Added", "message": f"Client '{client_label}' added."})
                else:
                    results.append({"inbound": inbound_name, "status": "Failed", "action": "Not Added", "message": f"Add failed (see log)."})
            except Exception as e:
                results.append({"inbound": inbound_name, "status": "Failed", "action": "Error", "message": str(e)})
            progress.update(add_task, advance=1)

    display_summary_table(results, "Client Add Results")


def handle_update_client(xui_api):
    """Handles the 'Update Client' menu option."""
    selection_result = get_inbound_selection(xui_api)
    if selection_result is None:
        return

    selected_inbound_ids, all_inbounds = selection_result

    client_identifier = Prompt.ask("Enter client UUID (id) or Label (email) to update")
    if not client_identifier:
        console.print("[bold red]Client identifier cannot be empty. Returning to main menu.[/bold red]")
        return

    new_secret = Prompt.ask("Enter NEW secret (Trojan password / VMess id). Leave blank to keep current.", default="")

    console.print(f"\n[bold white]Starting client update for '{client_identifier}' across {len(selected_inbound_ids)} inbound(s)...[/bold white]")

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), "{task.completed}/{task.total}", TextColumn("[progress.percentage]{task.percentage:>3.0f}%"), console=console, transient=True) as progress:
        update_task = progress.add_task("[cyan]Processing inbounds...", total=len(selected_inbound_ids))

        results = []
        for inbound_id in selected_inbound_ids:
            inbound_name = next((inb.get('remark', f"ID {inbound_id}") for inb in all_inbounds if inb['id'] == inbound_id), f"ID {inbound_id}")
            progress.update(update_task, description=f"[cyan]Updating '{inbound_name}'...[/cyan]")

            try:
                inbound_details = xui_api.get_inbound_details(inbound_id)
                if not inbound_details:
                    results.append({"inbound": inbound_name, "status": "Failed", "action": "Skipped", "message": "Could not fetch inbound details."})
                    progress.update(update_task, advance=1)
                    continue

                proto = inbound_details['protocol'].lower()
                settings = json.loads(inbound_details['settings'])
                clients = settings.get('clients', [])

                found = False
                for client in clients:
                    if client.get('id') == client_identifier or client.get('email') == client_identifier:
                        found = True
                        if new_secret:
                            if proto in ['vless', 'trojan']:
                                # vless has no password concept; trojan uses password
                                if proto == 'trojan':
                                    client['password'] = new_secret
                                elif proto == 'vless':
                                    client['id'] = new_secret  # set new UUID for VLESS
                            elif proto == 'vmess':
                                client['id'] = new_secret  # VMess id is UUID
                        break

                if not found:
                    results.append({"inbound": inbound_name, "status": "Failed", "action": "Not Found", "message": f"Client '{client_identifier}' not found."})
                else:
                    inbound_details['settings'] = settings
                    resp = xui_api.update_inbound(inbound_details)
                    if resp and resp.get('success'):
                        results.append({"inbound": inbound_name, "status": "Success", "action": "Updated", "message": "Client updated."})
                    else:
                        results.append({"inbound": inbound_name, "status": "Failed", "action": "Update", "message": "API update failed."})

            except Exception as e:
                results.append({"inbound": inbound_name, "status": "Failed", "action": "Error", "message": str(e)})

            progress.update(update_task, advance=1)

    display_summary_table(results, "Client Update Results")


# --- TUI Application Logic ---
def main():
    console.print(Panel("[bold green]X-UI Client Manager TUI[/bold green]\nManage clients across multiple X-UI inbounds with one command.", expand=False))
    console.print("-" * 60)

    # 1. Load/Setup Config
    config = load_config()

    # If config loading failed or file didn't exist, initialize an empty dict
    if config is None:
        console.print("[bold yellow]No configuration found or it's invalid. Please enter X-UI details:[/bold yellow]")
        config = {}

    # Now config is guaranteed to be a dict (either loaded or new empty one)
    if 'url' not in config:
        config['url'] = Prompt.ask(
            "Enter X-UI Panel URL (e.g., https://your-domain.com:port/jende/ — must end with a slash)",
            default=os.getenv("XUI_URL", "")
        )
        config['username'] = Prompt.ask("Enter X-UI Username", default=os.getenv("XUI_USERNAME", ""))
        config['password'] = getpass.getpass("Enter X-UI Password (will not be displayed): ")
        verify_ssl_input = Prompt.ask(
            "Verify SSL certificates? (y/n) — choose 'n' for self-signed",
            choices=["y", "n"], default="y"
        )
        config['verify_ssl'] = True if verify_ssl_input.lower() == 'y' else False
        save_config(config)
    else:
        console.print(f"[bold green]Loaded configuration for {config['url']}[/bold green]")
        if 'verify_ssl' not in config:
            verify_ssl_input = Prompt.ask("Verify SSL certificates? (y/n)", choices=["y", "n"], default="y")
            config['verify_ssl'] = True if verify_ssl_input.lower() == 'y' else False
            save_config(config)

    xui_api = XUIAPI(config['url'], config['username'], config['password'], verify_ssl=config.get('verify_ssl', True))

    # 2. Login
    with console.status("[bold blue]Attempting to log in to X-UI panel...[/bold blue]", spinner="dots"):
        if not xui_api.login():
            console.print("[bold red]Login failed. Please check credentials and URL.[/bold red]")
            sys.exit(1)

    # 3. Main Menu Loop
    while True:
        console.print("\n" + "-" * 30)
        console.print(Panel("[bold green]Menu[/bold green]", expand=False))
        menu_table = Table(show_header=False, show_lines=False, box=None)
        menu_table.add_column("Option", style="cyan")
        menu_table.add_column("Description", style="white")
        menu_table.add_row("0.", "Exit")
        menu_table.add_row("1.", "Update Client (by UUID or Label)")
        menu_table.add_row("2.", "Add New Client")
        console.print(menu_table)
        console.print("-" * 30)

        choice = Prompt.ask("Please enter your selection", choices=["0", "1", "2"], default="0")

        if choice == "0":
            console.print("[bold green]Exiting X-UI Client Manager. Goodbye! 👋[/bold green]")
            sys.exit(0)
        elif choice == "1":
            handle_update_client(xui_api)
        elif choice == "2":
            handle_add_client(xui_api)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Operation cancelled by user.[/bold yellow]")
        sys.exit(0)
