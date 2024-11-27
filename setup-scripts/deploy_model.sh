#!/bin/bash

# Enable error handling - exit on any error
set -e

# Set variables
USER="rkeshri98"                  # SSH username for the VM
VM_IP=34.45.132.19           # External IP address of the VM
REMOTE_DIR="/home/$USER/deployment"  # Remote directory for deployment
REPO_URL="https://github.com/MLOPS-IE7374-Fall2024-G9/mlops-project.git"  # GitHub repository URL
REQUIREMENTS_FILE="./airflow-config/requirements.txt"  # Path to requirements.txt
MODEL_SCRIPT="./model/scripts/mlflow_model_registry.py"  # Path to the script to fetch the latest model
PASSWORD="mlops"

# Helper function to execute a command over SSH
ssh_exec() {
    sshpass -p $PASSWORD ssh $USER@$VM_IP "$1"
}

# Step 1: Check if directory exists, perform git stash and then git pull
echo "Ensuring repository is up-to-date on the remote machine..."
ssh_exec "
    if [ -d $REMOTE_DIR ]; then
        echo 'Directory $REMOTE_DIR exists, stashing any local changes and pulling latest changes...'
        cd $REMOTE_DIR && \
        git stash && \
        git pull
    else
        echo 'Directory $REMOTE_DIR does not exist, cloning repository...'
        git clone $REPO_URL $REMOTE_DIR
    fi
"

# Step 2: Run setup.sh after repository update (if available)
echo "Running setup.sh script after repository update..."
ssh_exec "
    cd $REMOTE_DIR && \
    if [ -f setup.sh ]; then
        echo 'Running setup.sh...'
        chmod +x setup.sh && ./setup.sh
    else
        echo 'setup.sh not found in the repository.'
    fi
"

# Step 3: Activate virtual environment and run the model fetching script
echo "Activating virtual environment and running the model fetching script on the remote machine..."
ssh_exec "
    cd $REMOTE_DIR && \
    if [ -d venv ]; then
        echo 'Activating virtual environment...'
        source venv/bin/activate && \
        echo 'Running model fetching script...' && \
        python3 $MODEL_SCRIPT --operation fetch_latest
    else
        echo 'Virtual environment not found, please ensure it is set up correctly.'
    fi
"

echo "Deployment complete."