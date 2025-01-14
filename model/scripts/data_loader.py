# usage - python script_name.py path/to/dataset.csv --config path/to/config.json --save_locally

import pandas as pd
from sklearn.model_selection import train_test_split
import os
import argparse
import logging
import json
import subprocess

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def load_config(config_path):
    """Load configuration from a JSON file."""
    if not os.path.exists(config_path):
        logger.error(f"Configuration file '{config_path}' not found.")
        raise FileNotFoundError(f"Configuration file '{config_path}' not found.")
    
    with open(config_path, 'r') as file:
        config = json.load(file)
        
    # Validate the required fields in the config file
    if "test_size" not in config or "validation_size" not in config:
        logger.error("Config file must contain 'test_size' and 'validation_size'.")
        raise ValueError("Config file must contain 'test_size' and 'validation_size'.")
    
    return config["test_size"], config["validation_size"]

def load_and_split_dataset(path, test_size, validation_size, random_state=42, save_locally=False, sensitive_cols=["subba-name"]):
    # Check if the file exists
    if not os.path.exists(path):
        logger.error(f"The file at path '{path}' does not exist.")
        raise FileNotFoundError(f"The file at path '{path}' does not exist.")
    
    logger.info(f"Loading dataset from {path}")
    data = pd.read_csv(path)

    # Split the data into train and test sets
    logger.info("Splitting data into train and test sets")
    #train_data, test_data = train_test_split(data, sensitive_cols, test_size=test_size, random_state=random_state, stratify = sensitive_cols)
    sensitive_feature = data[sensitive_cols].copy()
    train_data, test_data, sensitive_train, sensitive_test = train_test_split(data, sensitive_feature, test_size=test_size, random_state=random_state, stratify=sensitive_feature)
    
    # Further split the train data into train and validation sets
    logger.info("Splitting train data into train and validation sets")
    sensitive_feature = train_data[sensitive_cols].copy()
    train_data, validation_data, sensitive_train, sensitive_val = train_test_split(train_data, sensitive_feature, test_size=validation_size / (1 - test_size), random_state=random_state, stratify=sensitive_feature)
    
    # Save the datasets locally if the flag is set
    if save_locally:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(script_dir, "../data")
        os.makedirs(data_dir, exist_ok=True)
        
        # File paths for the datasets
        train_path = os.path.join(data_dir, "train_data.csv")
        validation_path = os.path.join(data_dir, "validation_data.csv")
        test_path = os.path.join(data_dir, "test_data.csv")
        sensitive_train_path = os.path.join(data_dir, "sensitive_train.csv")
        sensitive_test_path = os.path.join(data_dir, "sensitive_test.csv")
        
        # Save new datasets
        train_data.to_csv(train_path, index=False)
        validation_data.to_csv(validation_path, index=False)
        test_data.to_csv(test_path, index=False)
        sensitive_train.to_csv(sensitive_train_path, index=False)
        sensitive_test.to_csv(sensitive_test_path, index=False)
        
        logger.info(f"Datasets saved to {data_dir} directory.")
    
    return train_data, validation_data, test_data, sensitive_train, sensitive_test

def download_data():
    subprocess.run(["dvc", "pull"], check=True)

def main():
    parser = argparse.ArgumentParser(description="Load, split, and optionally save a dataset.")
    parser.add_argument("path", type=str, help="Path to the CSV file.")
    parser.add_argument("--config", type=str, default="config.json", help="Path to the configuration JSON file.")
    parser.add_argument("--save_locally", action="store_true", help="Flag to save the split datasets locally in ./data/ directory.")
    
    args = parser.parse_args()
    
    # Load configuration for test_size and validation_size from the specified config file
    try:
        #download_data()
        test_size, validation_size = load_config(args.config)
        train_data, validation_data, test_data, sensitive_train, sensitive_test = load_and_split_dataset(args.path, test_size, validation_size, save_locally=args.save_locally)
        print(train_data.info(), sensitive_train.info(), test_data.info(), sensitive_test.info())
        logger.info("Dataset loaded, split, and processed successfully.")
    except (FileNotFoundError, ValueError) as e:
        logger.error(e)

if __name__ == "__main__":
    main()