#!/usr/bin/env python3
import requests
import json
import os
import getpass
import uuid
import sys

from rich.console import Console
from rich.prompt import Prompt
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.panel import Panel

# Global console for rich output
console = Console()

# --- Configuration Handling ---
CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".xui_tui_config.json") # Store config in user's home directory

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
    def __init__(self, base_url, username, password):
        # Ensure base_url is just the protocol://host:port part
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.login_status = False

    def _request(self, method, endpoint, json_data=None, data=None):
        """Helper method to make API requests and handle common errors."""
        url = f"{self.base_url}{endpoint}"
        try:
            if method == "POST":
                response = self.session.post(url, json=json_data, data=data, timeout=10)
            elif method == "GET":
                response = self.session.get(url, timeout=10)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            response.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)
            
            # X-UI API typically returns JSON with a 'success' field
            res_json = response.json()
            if not res_json.get('success', False):
                msg = res_json.get('msg', 'Unknown X-UI API error.')
                raise requests.exceptions.RequestException(f"X-UI API Error: {msg}")
            return res_json
        except requests.exceptions.HTTPError as e:
            console.print(f"[bold red]HTTP Error for {url}: {e.response.status_code} - {e.response.text}[/bold red]")
            return None
        except requests.exceptions.ConnectionError as e:
            console.print(f"[bold red]Connection Error for {url}: {e}. Check URL and network connection.[/bold red]")
            return None
        except requests.exceptions.Timeout:
            console.print(f"[bold red]Request timed out for {url}.[/bold red]")
            return None
        except requests.exceptions.RequestException as e:
            console.print(f"[bold red]Request Error for {url}: {e}[/bold red]")
            return None
        except json.JSONDecodeError:
            # If the response text is empty or not JSON, print it for debugging
            console.print(f"[bold red]Error: Received non-JSON response from {url}. Response Status: {response.status_code}. Response Content: '{response.text}'[/bold red]")
            return None
        except Exception as e:
            console.print(f"[bold red]An unexpected error occurred for {url}: {e}[/bold red]")
            return None

    def login(self):
        """Authenticates with the X-UI panel."""
        console.print("[bold blue]Logging in to X-UI...[/bold blue]")
        endpoint = "/login"
        data = {"username": self.username, "password": self.password}
        
        try:
            # Login usually requires sending form data, not JSON
            response = self.session.post(f"{self.base_url}{endpoint}", data=data, timeout=10)
            response.raise_for_status()

            res_json = response.json()
            if res_json.get('success'):
                self.login_status = True
                console.print("[bold green]Login successful![/bold green]")
                return True
            else:
                msg = res_json.get('msg', 'Authentication failed.')
                console.print(f"[bold red]Login failed: {msg}[/bold red]")
                self.login_status = False
                return False
        except requests.exceptions.RequestException as e:
            console.print(f"[bold red]Login request failed: {e}[/bold red]")
            self.login_status = False
            return False

    def get_inbounds(self):
        """Fetches a list of all inbounds."""
        if not self.login_status:
            console.print("[bold red]Not logged in. Please log in first.[/bold red]")
            return None
        return self._request("GET", "/panel/api/inbounds/list")

    def get_inbound_details(self, inbound_id):
        """Fetches the detailed configuration for a specific inbound."""
        if not self.login_status:
            console.print("[bold red]Not logged in. Please log in first.[/bold red]")
            return None
        
        # X-UI API for single inbound details often uses /panel/api/inbounds/get/<id>
        # However, it might also be that list provides enough, or update needs full object.
        # Assuming list is sufficient, let's filter it. If update needs *more* details,
        # a dedicated get endpoint would be needed. For now, we'll get from the list first.
        
        inbounds_list_res = self.get_inbounds()
        if inbounds_list_res and inbounds_list_res.get('obj'):
            for inbound in inbounds_list_res['obj']:
                if inbound['id'] == inbound_id:
                    return inbound
        return None

    def update_inbound(self, inbound_config):
        """Updates the configuration of an inbound."""
        if not self.login_status:
            console.print("[bold red]Not logged in. Please log in first.[/bold red]")
            return None
        
        # The X-UI API's update endpoint typically expects the entire inbound object
        # The endpoint is usually /panel/api/inbounds/update
        endpoint = "/panel/api/inbounds/update"
        return self._request("POST", endpoint, json_data=inbound_config)

# --- TUI Application Logic ---
def main():
    console.print(Panel("[bold green]X-UI Client Manager TUI[/bold green]\n"
                        "Manage clients across multiple X-UI inbounds with one command.",
                        expand=False))
    console.print("-" * 60)

    # 1. Load/Setup Config
    config = load_config()
    if not config:
        # Prompt for details if no config or corrupted config
        console.print("[bold yellow]No configuration found or it's invalid. Please enter X-UI details:[/bold yellow]")
        config = {}
        config['url'] = Prompt.ask(
            "Enter X-UI Panel URL (e.g., [green]https://your-domain.com:port[/green] or [green]http://your-ip:port[/green])",
            default=os.getenv("XUI_URL", "")
        )
        config['username'] = Prompt.ask("Enter X-UI Username", default=os.getenv("XUI_USERNAME", ""))
        config['password'] = getpass.getpass("Enter X-UI Password (will not be displayed): ")
        save_config(config)
    else:
        console.print(f"[bold green]Loaded configuration for {config['url']}[/bold green]")

    xui_api = XUIAPI(config['url'], config['username'], config['password'])

    # 2. Login
    with console.status("[bold blue]Attempting to log in to X-UI panel...[/bold blue]", spinner="dots"):
        if not xui_api.login_status: # Check if we're already logged in from previous session attempt
            if not xui_api.login():
                console.print("[bold red]Login failed. Please check credentials and URL.[/bold red]")
                sys.exit(1) # Exit if login fails

    # 3. Fetch Inbounds
    console.print("\n[bold blue]Fetching inbounds...[/bold blue]")
    inbounds_res = xui_api.get_inbounds()
    
    if not inbounds_res or not inbounds_res.get('obj'):
        console.print("[bold yellow]No inbounds found or error fetching inbounds.[/bold yellow]")
        sys.exit(0)
    
    inbounds = inbounds_res['obj']

    # Display inbounds and allow selection
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
            inbound['remark'],
            inbound['protocol'].upper(),
            str(inbound['port'])
        )

    console.print(inbound_table)

    selected_indices_str = Prompt.ask(
        "\n[bold white]Enter comma-separated indices of inbounds to update[/bold white] "
        "(e.g., [green]1,3,4[/green] or [green]all[/green] for all inbounds)",
        default="all"
    )

    selected_inbound_ids = []
    if selected_indices_str.lower() == "all":
        selected_inbound_ids = [inb['id'] for inb in inbounds]
    else:
        try:
            indices = [int(x.strip()) for x in selected_indices_str.split(',')]
            for idx in indices:
                if 1 <= idx <= len(inbounds):
                    selected_inbound_ids.append(inbounds[idx - 1]['id'])
                else:
                    console.print(f"[bold yellow]Warning: Index {idx} is out of range. Skipping.[/bold yellow]")
        except ValueError:
            console.print("[bold red]Invalid input for inbound selection. Exiting.[/bold red]")
            sys.exit(1)

    if not selected_inbound_ids:
        console.print("[bold yellow]No inbounds selected. Exiting.[/bold red]")
        sys.exit(0)

    # 4. Get Client Details
    console.print("\n[bold white]Client Details:[/bold white]")
    client_identifier = Prompt.ask(
        "Enter client [cyan]UUID[/cyan] or [cyan]Email[/cyan] to update/create (e.g., [green]john@example.com[/green] or [green]your-uuid[/green])",
        default=""
    )
    if not client_identifier:
        console.print("[bold red]Client identifier cannot be empty. Exiting.[/bold red]")
        sys.exit(1)

    new_password = Prompt.ask(
        "Enter [bold magenta]NEW[/bold magenta] client password (leave empty to keep current or generate random if new client)",
        default=""
    )

    # 5. Process Updates
    console.print(f"\n[bold white]Starting client update for '{client_identifier}' across {len(selected_inbound_ids)} inbounds...[/bold white]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        "{task.completed}/{task.total}",
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
        transient=True
    ) as progress:
        update_task = progress.add_task("[cyan]Processing inbounds...", total=len(selected_inbound_ids))

        results = []
        for inbound_id in selected_inbound_ids:
            inbound_name = next((inb['remark'] for inb in inbounds if inb['id'] == inbound_id), f"ID {inbound_id}")
            progress.update(update_task, description=f"[cyan]Updating '{inbound_name}'...[/cyan]")
            
            result_status = "Failed"
            result_action = "N/A"
            result_message = ""

            try:
                # Fetch full inbound details
                inbound_details = xui_api.get_inbound_details(inbound_id)
                if not inbound_details:
                    result_message = "Could not fetch inbound details."
                    raise Exception(result_message)
                
                # Check for VLESS or other protocols supporting clients
                if inbound_details['protocol'].lower() not in ['vless', 'vmess', 'trojan']:
                    result_message = f"Inbound protocol '{inbound_details['protocol']}' does not support client management via this script."
                    raise Exception(result_message)

                # Parse settings to modify clients
                settings = json.loads(inbound_details['settings'])
                clients = settings.get('clients', [])

                client_found = False
                for client in clients:
                    # Match by UUID (id) or email
                    if (client.get('id') == client_identifier) or \
                       (client.get('email') == client_identifier and client_identifier):
                        
                        console.print(f"  [bold blue]Client '{client_identifier}' found in '{inbound_name}'. Updating...[/bold blue]")
                        client_found = True
                        result_action = "Updated"

                        if new_password:
                            # Update password only for VLESS/Trojan (VMess uses alterId/ID)
                            if inbound_details['protocol'].lower() == 'vless' or inbound_details['protocol'].lower() == 'trojan':
                                client['password'] = new_password
                                result_message = f"Client password updated to: {new_password}"
                            elif inbound_details['protocol'].lower() == 'vmess':
                                client['id'] = new_password # For VMess, 'id' is the password/UUID
                                result_message = f"VMess client ID (password) updated to: {new_password}"
                            else:
                                result_message = f"Password update not supported for protocol {inbound_details['protocol']}. Client updated."
                        else:
                            # If no new password, ensure one exists for new/existing clients
                            if (inbound_details['protocol'].lower() == 'vless' or inbound_details['protocol'].lower() == 'trojan') and ('password' not in client or not client['password']):
                                client['password'] = str(uuid.uuid4()) # Generate if missing
                                result_message = f"Client password kept or generated: {client['password']}"
                            elif inbound_details['protocol'].lower() == 'vmess' and ('id' not in client or not client['id']):
                                client['id'] = str(uuid.uuid4()) # Generate VMess ID if missing
                                result_message = f"VMess client ID (password) kept or generated: {client['id']}"
                            else:
                                result_message = "Client details updated (password not changed/generated)."
                        break

                if not client_found:
                    console.print(f"  [bold yellow]Client '{client_identifier}' not found in '{inbound_name}'. Creating new client...[/bold yellow]")
                    result_action = "Created"
                    
                    # Determine UUID and password for new client
                    new_client_uuid = str(uuid.uuid4())
                    generated_password = new_password if new_password else str(uuid.uuid4())

                    new_client = {}

                    # Logic based on protocol
                    if inbound_details['protocol'].lower() == 'vless':
                        new_client = {
                            "id": new_client_uuid,
                            "email": client_identifier,
                            "flow": "", # Assuming default empty flow
                            "level": 0, # Default level
                            "password": generated_password
                        }
                    elif inbound_details['protocol'].lower() == 'vmess':
                        new_client = {
                            "id": generated_password, # VMess uses 'id' as the actual password/UUID
                            "email": client_identifier,
                            "alterId": 0, # Default alterId
                            "level": 0
                        }
                    elif inbound_details['protocol'].lower() == 'trojan':
                        new_client = {
                            "password": generated_password,
                            "email": client_identifier,
                            "level": 0
                        }
                    
                    # If the client_identifier *looks* like a UUID, we should use it for the 'id' field
                    # for VLESS, and generate an email. Otherwise, use it as email and generate UUID for 'id'
                    try:
                        valid_uuid = uuid.UUID(client_identifier)
                        if inbound_details['protocol'].lower() == 'vless':
                            new_client['id'] = str(valid_uuid)
                            new_client['email'] = f"client-{str(valid_uuid)[:8]}@xui.com"
                        elif inbound_details['protocol'].lower() == 'vmess':
                            # VMess id is password, so if client_identifier is UUID, it's used as password
                            new_client['id'] = str(valid_uuid)
                            new_client['email'] = f"client-{str(valid_uuid)[:8]}@xui.com"
                        elif inbound_details['protocol'].lower() == 'trojan':
                            # Trojan doesn't have an 'id' field like VLESS. Password is the main identifier.
                            # So we just assign email.
                            new_client['email'] = f"client-{str(valid_uuid)[:8]}@xui.com"
                            new_client['password'] = generated_password # Ensure password is set
                    except ValueError:
                        # client_identifier is not a UUID, assume it's an email
                        new_client['email'] = client_identifier
                        # UUID for VLESS is already generated (new_client_uuid) or used as password for VMess (generated_password)
                    
                    clients.append(new_client)
                    result_message = f"New client created. Email: {new_client['email']}"
                    if inbound_details['protocol'].lower() == 'vless':
                        result_message += f", UUID: {new_client['id']}"
                    result_message += f", Password: {new_client.get('password', new_client.get('id', 'N/A'))}"


                settings['clients'] = clients
                inbound_details['settings'] = json.dumps(settings)

                # Update the inbound in X-UI
                response = xui_api.update_inbound(inbound_details)
                if not response or response.get('success') is False:
                    raise Exception(response.get('msg', 'Unknown API error during update.'))

                result_status = "Success"

            except Exception as e:
                console.print(f"  [bold red]Error updating '{inbound_name}': {e}[/bold red]")
                result_status = "Failed"
                result_message = str(e)

            results.append({"inbound": inbound_name, "status": result_status, "action": result_action, "message": result_message})
            progress.update(update_task, advance=1)

    # 6. Display Summary
    console.print(Panel("[bold white]Client Update Summary[/bold white]", expand=False))
    summary_table = Table(title="Client Update Results", show_lines=True)
    summary_table.add_column("Inbound", style="cyan")
    summary_table.add_column("Status", style="magenta")
    summary_table.add_column("Action", style="green")
    summary_table.add_column("Message", style="blue")

    for res in results:
        status_style = "green" if res['status'] == "Success" else "red"
        summary_table.add_row(res['inbound'], f"[{status_style}]{res['status']}[/{status_style}]", res['action'], res['message'])
    console.print(summary_table)
    console.print("\n[bold green]Operation complete![/bold green]")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Operation cancelled by user.[/bold yellow]")
        sys.exit(0)
