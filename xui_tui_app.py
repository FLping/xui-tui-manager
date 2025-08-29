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
CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".xui_tui_config.json")

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            console.print(f"[bold red]Error: Could not parse {CONFIG_FILE}. It might be corrupted.[/bold red]")
            return None
    return None

def save_config(config):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
        console.print(f"[bold green]Configuration saved to {CONFIG_FILE}[/bold green]")
    except IOError as e:
        console.print(f"[bold red]Error: Could not save configuration to {CONFIG_FILE}: {e}[/bold red]")

# --- X-UI API Client ---
class XUIAPI:
    def __init__(self, base_url, username, password, verify_ssl=True):
        self.base_url = base_url.rstrip('/') + '/'
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.verify_ssl = verify_ssl

        parsed_url = urlparse(self.base_url)
        host_header = parsed_url.netloc

        self.session.headers.update({
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Host': host_header
        })
        self.login_status = False

    def _request(self, method, endpoint, json_data=None, data=None):
        url = urljoin(self.base_url, endpoint)
        original_content_type = self.session.headers.get('Content-Type')

        try:
            response = None
            if method == "POST":
                if json_data is not None:
                    self.session.headers.update({'Content-Type': 'application/json'})
                    response = self.session.post(url, json=json_data, timeout=10, verify=self.verify_ssl)
                elif data is not None:
                    self.session.headers.update({'Content-Type': 'application/x-www-form-urlencoded'})
                    response = self.session.post(url, data=data, timeout=10, verify=self.verify_ssl)
                else:
                    response = self.session.post(url, timeout=10, verify=self.verify_ssl)
            elif method == "GET":
                response = self.session.get(url, timeout=10, verify=self.verify_ssl)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            self.session.headers.update({'Content-Type': original_content_type})

            response.raise_for_status()

            if not response.text.strip():
                raise json.JSONDecodeError("Empty response body, expecting JSON response from server.", response.text, 0)

            res_json = response.json()
            if not res_json.get('success', False):
                msg = res_json.get('msg', 'Unknown X-UI API error.')
                raise requests.exceptions.RequestException(f"X-UI API Error: {msg}")
            return res_json
        except Exception as e:
            console.print(f"[bold red]Request failed for {url}: {e}[/bold red]")
            self.session.headers.update({'Content-Type': original_content_type})
            return None

    def login(self):
        console.print("[bold blue]Logging in to X-UI...[/bold blue]")
        data = {"username": self.username, "password": self.password}
        response = self._request("POST", "login", data=data)

        if response and response.get('success'):
            self.login_status = True
            console.print("[bold green]Login successful![/bold green]")
            return True
        else:
            msg = response.get('msg', 'Authentication failed.') if response else 'No response from server.'
            console.print(f"[bold red]Login failed: {msg}[/bold red]")
            return False

    def get_inbounds(self):
        if not self.login_status:
            console.print("[bold red]Not logged in.[/bold red]")
            return None
        return self._request("GET", "panel/api/inbounds/list")

    def get_inbound_details(self, inbound_id):
        if not self.login_status:
            console.print("[bold red]Not logged in.[/bold red]")
            return None
        res = self.get_inbounds()
        if res and res.get('obj'):
            for inbound in res['obj']:
                if inbound['id'] == inbound_id:
                    return inbound
        return None

    def update_inbound(self, inbound_config: dict):
        if not self.login_status:
            console.print("[bold red]Not logged in.[/bold red]")
            return None

        settings = inbound_config.get("settings")
        if isinstance(settings, dict):
            settings_str = json.dumps(settings)
        else:
            settings_str = settings

        payload = {
            "id": inbound_config["id"],
            "settings": settings_str
        }

        return self._request("POST", "panel/api/inbounds/update", data=payload)

    def add_client(self, inbound_id: int, client_email: str, client_password: str = None, **kwargs):
        if not self.login_status:
            console.print("[bold red]Not logged in.[/bold red]")
            return False

        inbound = self.get_inbound_details(inbound_id)
        if not inbound:
            console.print(f"[bold red]Inbound {inbound_id} not found.[/bold red]")
            return False

        protocol = inbound["protocol"].lower()
        settings = json.loads(inbound["settings"])
        clients = settings.get("clients", [])

        new_client_uuid = str(uuid.uuid4())
        generated_password = client_password if client_password else str(uuid.uuid4())

        client_obj = {
            "email": client_email,
            "enable": True,
            "flow": kwargs.get("flow", ""),
            "limitIp": kwargs.get("limitIp", 0),
            "totalGB": kwargs.get("totalGB", 0),
            "expiryTime": kwargs.get("expiryTime", 0),
            "tgId": kwargs.get("tgId", ""),
            "subId": kwargs.get("subId", str(uuid.uuid4())[:12]),
            "reset": 0
        }

        if protocol == "vless":
            client_obj["id"] = new_client_uuid
            client_obj["uuid"] = new_client_uuid
            client_obj["password"] = generated_password
        elif protocol == "vmess":
            client_obj["id"] = generated_password
            client_obj["alterId"] = kwargs.get("alterId", 0)
        elif protocol == "trojan":
            client_obj["password"] = generated_password
        else:
            console.print(f"[bold red]Unsupported protocol: {protocol}[/bold red]")
            return False

        clients.append(client_obj)
        settings["clients"] = clients

        payload = {
            "id": inbound_id,
            "settings": json.dumps(settings)
        }

        response = self._request("POST", "panel/api/inbounds/addClient", data=payload)
        if response and response.get("success"):
            console.print(f"[bold green]Client '{client_email}' added to inbound {inbound_id}.[/bold green]")
            return True
        else:
            msg = response.get("msg", "Unknown error") if response else "No response"
            console.print(f"[bold red]Failed to add client: {msg}[/bold red]")
            return False

# --- Helper Functions for TUI Menu Logic ---
def get_inbound_selection(xui_api):
    console.print("\n[bold blue]Fetching inbounds...[/bold blue]")
    inbounds_res = xui_api.get_inbounds()
    if not inbounds_res or not isinstance(inbounds_res, dict) or not inbounds_res.get('obj'):
        console.print("[bold yellow]No inbounds found.[/bold yellow]")
        return None

    inbounds = inbounds_res['obj']
    inbound_table = Table(title="Available Inbounds", show_lines=True)
    inbound_table.add_column("Index", style="cyan", justify="center")
    inbound_table.add_column("ID", style="magenta")
    inbound_table.add_column("Name", style="green")
    inbound_table.add_column("Protocol", style="yellow")
    inbound_table.add_column("Port", style="blue")

    for i, inbound in enumerate(inbounds):
        inbound_table.add_row(str(i+1), str(inbound['id']), inbound['remark'], inbound['protocol'].upper(), str(inbound['port']))

    console.print(inbound_table)

    selected_indices_str = Prompt.ask("Enter indices (e.g. 1,2 or all)", default="all")
    selected_inbound_ids = []

    if selected_indices_str.lower() == "all":
        selected_inbound_ids = [inb['id'] for inb in inbounds]
    else:
        try:
            indices = [int(x.strip()) for x in selected_indices_str.split(',')]
            for idx in indices:
                if 1 <= idx <= len(inbounds):
                    selected_inbound_ids.append(inbounds[idx - 1]['id'])
        except ValueError:
            console.print("[bold red]Invalid input[/bold red]")
            return None

    return selected_inbound_ids, inbounds

def handle_add_client(xui_api):
    selection_result = get_inbound_selection(xui_api)
    if selection_result is None:
        return

    selected_inbound_ids, all_inbounds = selection_result
    client_email = Prompt.ask("Enter Email for new client")
    client_password = Prompt.ask("Enter password (blank for auto)", default="")

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("Adding clients...", total=len(selected_inbound_ids))
        for inbound_id in selected_inbound_ids:
            xui_api.add_client(inbound_id, client_email, client_password or None)
            progress.update(task, advance=1)

def handle_update_client(xui_api):
    selection_result = get_inbound_selection(xui_api)
    if selection_result is None:
        return

    selected_inbound_ids, all_inbounds = selection_result
    client_identifier = Prompt.ask("Enter client UUID or Email to update")
    new_password = Prompt.ask("Enter new password (blank = unchanged)", default="")

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("Updating clients...", total=len(selected_inbound_ids))
        for inbound_id in selected_inbound_ids:
            inbound = xui_api.get_inbound_details(inbound_id)
            if not inbound:
                continue
            settings = json.loads(inbound['settings'])
            updated = False
            for client in settings.get('clients', []):
                if client.get('id') == client_identifier or client.get('email') == client_identifier:
                    if new_password:
                        if inbound['protocol'].lower() in ["vless", "trojan"]:
                            client['password'] = new_password
                        elif inbound['protocol'].lower() == "vmess":
                            client['id'] = new_password
                    updated = True
            if updated:
                inbound['settings'] = settings
                xui_api.update_inbound(inbound)
            progress.update(task, advance=1)

# --- Main TUI ---
def main():
    console.print(Panel("[bold green]X-UI Client Manager TUI[/bold green]"))
    config = load_config() or {}
    if 'url' not in config:
        config['url'] = Prompt.ask("Enter X-UI URL")
        config['username'] = Prompt.ask("Enter X-UI Username")
        config['password'] = getpass.getpass("Enter X-UI Password: ")
        verify_ssl_input = Prompt.ask("Verify SSL? (y/n)", choices=["y","n"], default="y")
        config['verify_ssl'] = True if verify_ssl_input == 'y' else False
        save_config(config)
    else:
        if 'verify_ssl' not in config:
            verify_ssl_input = Prompt.ask("Verify SSL? (y/n)", choices=["y","n"], default="y")
            config['verify_ssl'] = True if verify_ssl_input == 'y' else False
            save_config(config)

    xui_api = XUIAPI(config['url'], config['username'], config['password'], verify_ssl=config.get('verify_ssl', True))
    if not xui_api.login():
        sys.exit(1)

    while True:
        console.print(Panel("[bold green]Menu[/bold green]"))
        menu_table = Table(show_header=False)
        menu_table.add_row("0", "Exit")
        menu_table.add_row("1", "Update Client")
        menu_table.add_row("2", "Add Client")
        console.print(menu_table)
        choice = Prompt.ask("Select", choices=["0","1","2"], default="0")

        if choice == "0":
            sys.exit(0)
        elif choice == "1":
            handle_update_client(xui_api)
        elif choice == "2":
            handle_add_client(xui_api)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Cancelled by user[/bold yellow]")
        sys.exit(0)
