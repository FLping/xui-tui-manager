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
    def __init__(self, base_url, username, password, verify_ssl=True):
        self.base_url = base_url.rstrip('/') + '/' # Ensure it always has a trailing slash for urljoin
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.verify_ssl = verify_ssl # Store SSL verification setting
        
        parsed_url = urlparse(self.base_url)
        host_header = parsed_url.netloc 
        
        self.session.headers.update({
            'Accept': 'application/json',
            # Default Content-Type to form-urlencoded, as many X-UI POSTs expect this for login
            'Content-Type': 'application/x-www-form-urlencoded', 
            'Host': host_header 
        })
        self.login_status = False

    def _request(self, method, endpoint, json_data=None, data=None):
        """
        Helper method to make API requests and handle common errors.
        Can send either JSON data (json_data) or form-urlencoded data (data).
        """
        url = urljoin(self.base_url, endpoint)
        console.print(f"[bold blue]DEBUG: Requesting URL: {url}[/bold blue]") 
        
        # Store current Content-Type to restore it later
        original_content_type = self.session.headers.get('Content-Type')
        
        try:
            response = None
            if method == "POST":
                if json_data is not None:
                    # Explicitly set Content-Type for JSON payloads
                    self.session.headers.update({'Content-Type': 'application/json'})
                    response = self.session.post(url, json=json_data, timeout=10, verify=self.verify_ssl)
                elif data is not None:
                    # Explicitly set Content-Type for form-urlencoded data
                    self.session.headers.update({'Content-Type': 'application/x-www-form-urlencoded'})
                    response = self.session.post(url, data=data, timeout=10, verify=self.verify_ssl)
                else:
                    # Default to form-urlencoded if no specific data type given for POST
                    self.session.headers.update({'Content-Type': 'application/x-www-form-urlencoded'})
                    response = self.session.post(url, timeout=10, verify=self.verify_ssl)
            elif method == "GET":
                response = self.session.get(url, timeout=10, verify=self.verify_ssl)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            # Restore original Content-Type header after the request
            self.session.headers.update({'Content-Type': original_content_type})

            response.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)
            
            # --- DEBUGGING LINES REMOVED for general use ---
            # console.print(f"[bold yellow]DEBUG: Response Status for {url}: {response.status_code}[/bold yellow]")
            # console.print(f"[bold yellow]DEBUG: Raw Response Text for {url}: '{response.text}'[/bold yellow]")
            # --- END DEBUGGING LINES ---

            # Check if response text is empty before trying to parse JSON
            if not response.text.strip():
                # If 200 OK and empty, do NOT automatically treat as success for updates.
                # This was a previous attempt to work around server behavior, but it masked failures.
                # Now, we expect *some* JSON response for updates, even if it's just {"success": true}.
                raise json.JSONDecodeError("Empty response body, expecting JSON response from server.", response.text, 0)


            res_json = response.json()
            if not res_json.get('success', False):
                msg = res_json.get('msg', 'Unknown X-UI API error.')
                raise requests.exceptions.RequestException(f"X-UI API Error: {msg}")
            return res_json
        except requests.exceptions.HTTPError as e:
            console.print(f"[bold red]HTTP Error for {url}: {e.response.status_code} - {e.response.text}[/bold red]")
            self.session.headers.update({'Content-Type': original_content_type}) # Restore on error
            return None
        except requests.exceptions.ConnectionError as e:
            console.print(f"[bold red]Connection Error for {url}: {e}. Check URL, network connection, and SSL certificate.[/bold red]")
            self.session.headers.update({'Content-Type': original_content_type}) # Restore on error
            return None
        except requests.exceptions.Timeout:
            console.print(f"[bold red]Request timed out for {url}.[/bold red]")
            self.session.headers.update({'Content-Type': original_content_type}) # Restore on error
            return None
        except requests.exceptions.RequestException as e:
            if "SSL" in str(e) or "certificate" in str(e):
                console.print(f"[bold red]SSL/TLS Error for {url}: {e}. Try disabling SSL verification if you are using a self-signed certificate or custom HTTPS setup.[/bold red]")
            else:
                console.print(f"[bold red]Request Error for {url}: {e}[/bold red]")
            self.session.headers.update({'Content-Type': original_content_type}) # Restore on error
            return None
        except json.JSONDecodeError as e:
            # Re-introduced debug for JSONDecodeError as it's the current problem.
            console.print(f"[bold red]Error: JSON parsing failed from {url}. Status: {response.status_code}. Content: '{response.text}'. Error: {e}[/bold red]")
            self.session.headers.update({'Content-Type': original_content_type}) # Restore on error
            return None
        except Exception as e:
            console.print(f"[bold red]An unexpected error occurred for {url}: {e}[/bold red]")
            self.session.headers.update({'Content-Type': original_content_type}) # Restore on error
            return None

    def login(self):
        """Authenticates with the X-UI panel."""
        console.print("[bold blue]Logging in to X-UI...[/bold blue]")
        endpoint = "login" # Endpoint relative to base_url
        data = {"username": self.username, "password": self.password}
        
        response = self._request("POST", endpoint, data=data) 
        
        if response and response.get('success'):
            self.login_status = True
            console.print("[bold green]Login successful![/bold green]")
            return True
        else:
            msg = response.get('msg', 'Authentication failed.') if response else 'No response or unsuccessful login from server.'
            console.print(f"[bold red]Login failed: {msg}[/bold red]")
            self.login_status = False
            return False

    def get_inbounds(self):
        """Fetches a list of all inbounds."""
        if not self.login_status:
            console.print("[bold red]Not logged in. Please log in first.[/bold red]")
            return None
        return self._request("GET", "panel/api/inbounds/list") 

    def get_inbound_details(self, inbound_id):
        """Fetches the detailed configuration for a specific inbound."""
        if not self.login_status:
            console.print("[bold red]Not logged in. Please log in first.[/bold red]")
            return None
        
        inbounds_list_res = self.get_inbounds()
        if inbounds_list_res and inbounds_list_res.get('obj'):
            for inbound in inbounds_list_res['obj']:
                if inbound['id'] == inbound_id:
                    return inbound
        return None

    def update_inbound(self, inbound_config: dict):
        """
        Updates the configuration of an inbound.
        Sends data as application/json, with 'settings' as a stringified JSON.
        """
        if not self.login_status:
            console.print("[bold red]Not logged in. Please log in first.[/bold red]")
            return None
        
        endpoint = "panel/api/inbounds/update" 
        
        # Create a mutable copy to modify
        payload_data = inbound_config.copy()
        
        # Ensure 'settings' field is stringified JSON within the main payload
        if 'settings' in payload_data and isinstance(payload_data['settings'], dict):
            payload_data['settings'] = json.dumps(payload_data['settings'])
        
        # Send the entire payload_data as JSON
        return self._request("POST", endpoint, json_data=payload_data) 

    def add_client_to_inbound(self, inbound_id, client_email, client_password=None):
        """Adds a new client to a specified inbound."""
        if not self.login_status:
            console.print("[bold red]Not logged in. Please log in first.[/bold red]")
            return False

        inbound_details = self.get_inbound_details(inbound_id)
        if not inbound_details:
            console.print(f"[bold red]Error: Could not fetch details for inbound ID {inbound_id}.[/bold red]")
            return False

        if inbound_details['protocol'].lower() not in ['vless', 'vmess', 'trojan']:
            console.print(f"[bold red]Inbound protocol '{inbound_details['protocol']}' does not support client management via this script.[/bold red]")
            return False

        # 'settings' field from API is a JSON string, so parse it
        settings = json.loads(inbound_details['settings'])
        clients = settings.get('clients', [])

        # Check if client with this email already exists
        for client in clients:
            if client.get('email') == client_email:
                console.print(f"[bold yellow]Warning: Client with email '{client_email}' already exists in inbound ID {inbound_id}.[/bold yellow]")
                return False # Or you could prompt to update

        new_client_uuid = str(uuid.uuid4())
        generated_password = client_password if client_password else str(uuid.uuid4())

        new_client = {}
        if inbound_details['protocol'].lower() == 'vless':
            new_client = {
                "id": new_client_uuid,
                "email": client_email,
                "flow": "", 
                "level": 0, 
                "password": generated_password
            }
        elif inbound_details['protocol'].lower() == 'vmess':
            new_client = {
                "id": generated_password, 
                "email": client_email,
                "alterId": 0, 
                "level": 0
            }
        elif inbound_details['protocol'].lower() == 'trojan':
            new_client = {
                "password": generated_password,
                "email": client_email,
                "level": 0
            }
        
        clients.append(new_client)
        settings['clients'] = clients
        
        # Update inbound_details with the modified settings dictionary (NOT stringified yet)
        # update_inbound will stringify it.
        inbound_details['settings'] = settings 

        response = self.update_inbound(inbound_details)
        if response and response.get('success'):
            console.print(f"[bold green]Client '{client_email}' added to inbound ID {inbound_id}.[/bold green]")
            return True
        else:
            console.print(f"[bold red]Failed to add client '{client_email}' to inbound ID {inbound_id}. Msg: {response.get('msg', 'Unknown error') if response else 'No response'}[/bold red]")
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
            inbound['remark'],
            inbound['protocol'].upper(),
            str(inbound['port'])
        )

    console.print(inbound_table)

    selected_indices_str = Prompt.ask(
        "\n[bold white]Enter comma-separated indices of inbounds to manage[/bold white] "
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
            console.print("[bold red]Invalid input for inbound selection. Returning to main menu.[/bold red]")
            return None
    
    if not selected_inbound_ids:
        console.print("[bold yellow]No inbounds selected. Returning to main menu.[/bold yellow]")
        return None

    return selected_inbound_ids, inbounds

def handle_update_client(xui_api):
    """Handles the 'Update Client' menu option."""
    selection_result = get_inbound_selection(xui_api)
    if selection_result is None:
        return

    selected_inbound_ids, all_inbounds = selection_result

    client_identifier = Prompt.ask(
        "Enter client [cyan]UUID[/cyan] or [cyan]Email[/cyan] to update (e.g., [green]john@example.com[/green] or [green]your-uuid[/green])"
    )
    if not client_identifier:
        console.print("[bold red]Client identifier cannot be empty. Returning to main menu.[/bold red]")
        return

    new_password = Prompt.ask(
        "Enter [bold magenta]NEW[/bold magenta] client password (leave empty to keep current)"
    )

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
            inbound_name = next((inb['remark'] for inb in all_inbounds if inb['id'] == inbound_id), f"ID {inbound_id}")
            progress.update(update_task, description=f"[cyan]Updating '{inbound_name}'...[/cyan]")
            
            result_status = "Failed"
            result_action = "N/A"
            result_message = ""

            try:
                inbound_details = xui_api.get_inbound_details(inbound_id)
                if not inbound_details:
                    result_message = "Could not fetch inbound details."
                    raise Exception(result_message)
                
                if inbound_details['protocol'].lower() not in ['vless', 'vmess', 'trojan']:
                    result_message = f"Inbound protocol '{inbound_details['protocol']}' does not support client management."
                    raise Exception(result_message)

                settings = json.loads(inbound_details['settings'])
                clients = settings.get('clients', [])

                client_found = False
                for client in clients:
                    if (client.get('id') == client_identifier) or \
                       (client.get('email') == client_identifier and client_identifier):
                        
                        console.print(f"  [bold blue]Client '{client_identifier}' found in '{inbound_name}'. Updating...[/bold blue]")
                        client_found = True
                        result_action = "Updated"

                        if new_password:
                            if inbound_details['protocol'].lower() == 'vless' or inbound_details['protocol'].lower() == 'trojan':
                                client['password'] = new_password
                                result_message = f"Client password updated to: {new_password}"
                            elif inbound_details['protocol'].lower() == 'vmess':
                                client['id'] = new_password 
                                result_message = f"VMess client ID (password) updated to: {new_password}"
                            else:
                                result_message = f"Password update not supported for protocol {inbound_details['protocol']}. Client updated."
                        else:
                            result_message = "Client details updated (password not changed)."
                        break

                if not client_found:
                    result_message = f"Client '{client_identifier}' not found in '{inbound_name}'. Not updated."
                    console.print(f"  [bold yellow]{result_message}[/bold yellow]")
                else:
                    settings['clients'] = clients
                    # Pass settings as a dictionary to inbound_details, update_inbound will stringify it
                    inbound_details['settings'] = settings 

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
    
    display_summary_table(results, "Client Update Results")

def handle_add_client(xui_api):
    """Handles the 'Add Client' menu option."""
    selection_result = get_inbound_selection(xui_api)
    if selection_result is None:
        return
    
    selected_inbound_ids, all_inbounds = selection_result

    client_email = Prompt.ask(
        "Enter [cyan]Email[/cyan] for the new client (e.g., [green]new_user@example.com[/green])"
    )
    if not client_email:
        console.print("[bold red]Client email cannot be empty. Returning to main menu.[/bold red]")
        return

    client_password = Prompt.ask(
        "Enter [bold magenta]password[/bold magenta] for the new client (leave empty to auto-generate)"
    )

    console.print(f"\n[bold white]Adding client '{client_email}' to {len(selected_inbound_ids)} inbounds...[/bold white]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        "{task.completed}/{task.total}",
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
        transient=True
    ) as progress:
        add_task = progress.add_task("[cyan]Processing inbounds...", total=len(selected_inbound_ids))

        results = []
        for inbound_id in selected_inbound_ids:
            inbound_name = next((inb['remark'] for inb in all_inbounds if inb['id'] == inbound_id), f"ID {inbound_id}")
            progress.update(add_task, description=f"[cyan]Adding to '{inbound_name}'...[/cyan]")
            
            result_status = "Failed"
            result_action = "N/A"
            result_message = ""

            try:
                # The actual add_client_to_inbound logic handles existence checks and protocol compatibility
                success = xui_api.add_client_to_inbound(inbound_id, client_email, client_password)
                if success:
                    result_status = "Success"
                    result_action = "Added"
                    result_message = f"Client '{client_email}' successfully added."
                else:
                    # add_client_to_inbound prints detailed messages directly on failure
                    result_status = "Failed"
                    result_action = "Not Added"
                    result_message = f"Failed to add client '{client_email}'." 

            except Exception as e:
                console.print(f"  [bold red]Error adding to '{inbound_name}': {e}[/bold red]")
                result_status = "Failed"
                result_message = str(e)

            results.append({"inbound": inbound_name, "status": result_status, "action": result_action, "message": result_message})
            progress.update(add_task, advance=1)
    
    display_summary_table(results, "Client Add Results")


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

# --- TUI Application Logic ---
def main():
    console.print(Panel("[bold green]X-UI Client Manager TUI[/bold green]\n"
                        "Manage clients across multiple X-UI inbounds with one command.",
                        expand=False))
    console.print("-" * 60)

    # 1. Load/Setup Config
    config = load_config()
    
    # If config loading failed or file didn't exist, initialize an empty dict
    if config is None:
        console.print("[bold yellow]No configuration found or it's invalid. Please enter X-UI details:[/bold yellow]")
        config = {} # Initialize config as an empty dictionary here

    # Now config is guaranteed to be a dict (either loaded or new empty one)
    # Check for 'url' to determine if it's a new config that hasn't been filled
    if 'url' not in config: # This checks if it's truly a new config that hasn't been filled
        config['url'] = Prompt.ask(
            "Enter X-UI Panel URL (e.g., [green]https://your-domain.com:port/jende/[/green] - **must** end with a slash)",
            default=os.getenv("XUI_URL", "")
        )
        config['username'] = Prompt.ask("Enter X-UI Username", default=os.getenv("XUI_USERNAME", ""))
        config['password'] = getpass.getpass("Enter X-UI Password (will not be displayed): ")
        
        verify_ssl_input = Prompt.ask(
            "[bold white]Verify SSL Certificates for HTTPS connections?[/bold white] "
            "([green]y[/green]/[red]n[/red], choose [red]n[/red] if using self-signed or internal certificates)",
            choices=["y", "n"], default="y"
        )
        config['verify_ssl'] = True if verify_ssl_input.lower() == 'y' else False
        save_config(config)
    else:
        console.print(f"[bold green]Loaded configuration for {config['url']}[/bold green]")
        # If config exists but verify_ssl is missing, prompt for it
        if 'verify_ssl' not in config:
            verify_ssl_input = Prompt.ask(
                "[bold white]Verify SSL Certificates for HTTPS connections?[/bold white] "
                "([green]y[/green]/[red]n[/red], choose [red]n[/red] if using self-signed or internal certificates)",
                choices=["y", "n"], default="y"
            )
            config['verify_ssl'] = True if verify_ssl_input.lower() == 'y' else False
            save_config(config)

    verify_ssl_setting = config.get('verify_ssl', True) # Now config is guaranteed to be a dict.

    xui_api = XUIAPI(config['url'], config['username'], config['password'], verify_ssl=verify_ssl_setting)

    # 2. Login
    with console.status("[bold blue]Attempting to log in to X-UI panel...[/bold blue]", spinner="dots"):
        if not xui_api.login():
            console.print("[bold red]Login failed. Please check credentials and URL.[/bold red]")
            sys.exit(1) # Exit if login fails

    # 3. Main Menu Loop
    while True:
        console.print("\n" + "-" * 30)
        console.print(Panel("[bold green]X-UI Client Management Menu[/bold green]", expand=False))
        menu_table = Table(show_header=False, show_lines=False, box=None)
        menu_table.add_column("Option", style="cyan")
        menu_table.add_column("Description", style="white")
        menu_table.add_row("0.", "Exit")
        menu_table.add_row("1.", "Update Client (by UUID or Email)")
        menu_table.add_row("2.", "Add New Client (by Email)")
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
        else:
            console.print("[bold red]Invalid choice. Please select 0, 1, or 2.[/bold red]")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Operation cancelled by user.[/bold yellow]")
        sys.exit(0)