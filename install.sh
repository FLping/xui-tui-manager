#!/bin/bash

# --- Configuration ---
GITHUB_REPO_URL="https://github.com/FLping/xui-tui-manager.git" # IMPORTANT: Replace with your actual GitHub repo URL
INSTALL_DIR="/opt/xui-tui-manager"
PYTHON_SCRIPT_NAME="xui_tui_app.py"
EXECUTABLE_NAME="xui-manager"

# --- Colors for better output ---
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting X-UI TUI Manager installation...${NC}"

# --- Check for root privileges ---
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}This script must be run as root. Please use 'sudo ./install_xui_tui.sh'.${NC}"
   exit 1
fi

# --- Install Git if not present ---
echo -e "${YELLOW}Checking for Git...${NC}"
if ! command -v git &> /dev/null; then
    echo -e "${YELLOW}Git not found. Installing...${NC}"
    if command -v apt-get &> /dev/null; then
        apt-get update && apt-get install -y git
    elif command -v yum &> /dev/null; then
        yum install -y git
    elif command -v dnf &> /dev/null; then
        dnf install -y git
    else
        echo -e "${RED}Error: Cannot find a package manager to install Git. Please install it manually.${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}Git is already installed.${NC}"
fi

# --- Install Python3 and pip if not present ---
echo -e "${YELLOW}Checking for Python3 and pip...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${YELLOW}Python3 not found. Installing...${NC}"
    if command -v apt-get &> /dev/null; then
        apt-get update && apt-get install -y python3 python3-pip
    elif command -v yum &> /dev/null; then
        yum install -y python3 python3-pip
    elif command -v dnf &> /dev/null; then
        dnf install -y python3 python3-pip
    else
        echo -e "${RED}Error: Cannot find a package manager to install Python3. Please install it manually.${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}Python3 is already installed.${NC}"
fi

if ! command -v pip3 &> /dev/null; then
    echo -e "${YELLOW}pip3 not found. Attempting to install pip3...${NC}"
    if command -v apt-get &> /dev/null; then
        apt-get install -y python3-pip
    elif command -v yum &> /dev/null; then
        yum install -y python3-pip
    elif command -v dnf &> /dev/null; then
        dnf install -y python3-pip
    fi
    if ! command -v pip3 &> /dev/null; then # Re-check after attempt
        echo -e "${RED}Error: pip3 installation failed or not found. Please install it manually.${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}pip3 is already installed.${NC}"
fi

# --- Install Python dependencies ---
echo -e "${YELLOW}Installing Python dependencies (requests, rich)...${NC}"
# Removed --break-system-packages as it's not supported by all pip versions.
pip3 install requests rich 
if [ $? -ne 0 ]; then
    echo -e "${RED}Error: Failed to install Python dependencies.${NC}"
    exit 1
fi
echo -e "${GREEN}Python dependencies installed successfully.${NC}"

# --- Clone the repository to a temporary location ---
TMP_CLONE_DIR=$(mktemp -d)
echo -e "${YELLOW}Cloning repository from ${GITHUB_REPO_URL} to ${TMP_CLONE_DIR}${NC}"
git clone "$GITHUB_REPO_URL" "$TMP_CLONE_DIR"
if [ $? -ne 0 ]; then
    echo -e "${RED}Error: Failed to clone the GitHub repository. Check URL and network access.${NC}"
    rm -rf "$TMP_CLONE_DIR" # Clean up temp directory
    exit 1
fi
echo -e "${GREEN}Repository cloned successfully.${NC}"

# --- Create installation directory ---
echo -e "${YELLOW}Creating installation directory: ${INSTALL_DIR}${NC}"
mkdir -p "$INSTALL_DIR"
if [ $? -ne 0 ]; then
    echo -e "${RED}Error: Failed to create installation directory.${NC}"
    rm -rf "$TMP_CLONE_DIR" # Clean up temp directory
    exit 1
fi

# --- Copy the Python script from the cloned repo to the install directory ---
echo -e "${YELLOW}Copying Python script to ${INSTALL_DIR}/${PYTHON_SCRIPT_NAME}${NC}"
cp "${TMP_CLONE_DIR}/${PYTHON_SCRIPT_NAME}" "$INSTALL_DIR/"
if [ $? -ne 0 ]; then
    echo -e "${RED}Error: Failed to copy Python script.${NC}"
    rm -rf "$TMP_CLONE_DIR" # Clean up temp directory
    exit 1
fi
echo -e "${GREEN}Python script copied successfully.${NC}"

# --- Clean up the temporary clone directory ---
echo -e "${YELLOW}Cleaning up temporary files...${NC}"
rm -rf "$TMP_CLONE_DIR"
echo -e "${GREEN}Temporary files cleaned.${NC}"

# --- Make the Python script executable ---
echo -e "${YELLOW}Setting executable permissions for ${INSTALL_DIR}/${PYTHON_SCRIPT_NAME}${NC}"
chmod +x "${INSTALL_DIR}/${PYTHON_SCRIPT_NAME}"
if [ $? -ne 0 ]; then
    echo -e "${RED}Error: Failed to set executable permissions.${NC}"
    exit 1
fi

# --- Create a symbolic link for easy execution ---
echo -e "${YELLOW}Creating symbolic link to /usr/local/bin/${EXECUTABLE_NAME}${NC}"
ln -sf "${INSTALL_DIR}/${PYTHON_SCRIPT_NAME}" "/usr/local/bin/${EXECUTABLE_NAME}"
if [ $? -ne 0 ]; then
    echo -e "${RED}Error: Failed to create symbolic link.${NC}"
    exit 1
fi
echo -e "${GREEN}Symbolic link created successfully.${NC}"

echo -e "\n${GREEN}X-UI TUI Manager installation complete! �${NC}"
echo -e "${GREEN}You can now run the application from any terminal with:${NC}"
echo -e "  ${YELLOW}${EXECUTABLE_NAME}${NC}"
echo -e "\n${YELLOW}Note: The configuration file will be stored in your home directory: ~/.xui_tui_config.json${NC}"
echo -e "${YELLOW}If you encounter 'pip' errors related to system packages, try running the install script again or manually install pip with 'sudo apt-get install python3-pip' or 'sudo yum install python3-pip'.${NC}"
�