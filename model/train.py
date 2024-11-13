# usage - 
# python train.py path/to/dataset.csv --config config.json --model lr 
# python train.py path/to/dataset.csv --config config.json --model lstm 
# python train.py path/to/dataset.csv --config config.json --model xgboost 


import argparse
import os
import pickle
import mlflow
import mlflow.sklearn
import mlflow.tensorflow
import mlflow.xgboost
import pandas as pd
from sklearn.linear_model import LinearRegression  # Updated to LinearRegression
from sklearn.metrics import accuracy_score
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
from sklearn.preprocessing import StandardScaler
import xgboost as xgb
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.callbacks import EarlyStopping
import json
from dataset_loader import load_and_split_dataset
import logging

# Setting up logger
logger = logging.getLogger("ModelTrainer")
logger.setLevel(logging.INFO)
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)

class ModelTrainer:
    def __init__(self, config_path, dataset_path, load_existing_model=False):
        self.config = self.load_config(config_path)
        
        self.dataset_path = dataset_path
        self.features = self.config["features"]
        self.label = self.config["label"]
        self.test_size = self.config["test_size"]
        self.validation_size = self.config["validation_size"]
        self.learning_rate = self.config["learning_rate"]
        self.load_existing_model = load_existing_model
        self.model_save_path = os.path.join(os.path.dirname(__file__), 'pickle')

        # Create the folder if it doesn't exist
        if not os.path.exists(self.model_save_path):
            os.makedirs(self.model_save_path)

        # Load and split dataset
        try:
            self.train_data, self.validation_data, self.test_data = load_and_split_dataset(
                dataset_path, self.test_size, self.validation_size, save_locally=False
            )
        except FileNotFoundError as e:
            logger.error(f"Error loading dataset: {e}")
            raise

    def load_config(self, config_path):
        """Load configuration from a JSON file."""
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Configuration file '{config_path}' not found.")
        
        with open(config_path, 'r') as file:
            config = json.load(file)
        
        return config

    def preprocess_data(self):
        # Define features and label
        X_train = self.train_data[self.features]
        y_train = self.train_data[self.label]
        X_val = self.validation_data[self.features]
        y_val = self.validation_data[self.label]
        X_test = self.test_data[self.features]
        y_test = self.test_data[self.label]
        
        # Standardizing the features
        scaler = StandardScaler()
        X_train = scaler.fit_transform(X_train)
        X_val = scaler.transform(X_val)
        X_test = scaler.transform(X_test)
        
        return X_train, X_val, X_test, y_train, y_val, y_test

    def save_model(self, model, model_type):
        """Save the trained model using pickle."""
        model_filename = os.path.join(self.model_save_path, f"{model_type}_model.pkl")
        with open(model_filename, 'wb') as f:
            pickle.dump(model, f)
        logger.info(f"Model saved to {model_filename}")

    def load_model(self, model_type):
        """Load the trained model from pickle."""
        model_filename = os.path.join(self.model_save_path, f"{model_type}_model.pkl")
        if os.path.exists(model_filename):
            with open(model_filename, 'rb') as f:
                model = pickle.load(f)
            logger.info(f"Model loaded from {model_filename}")
            return model
        else:
            logger.error(f"No model found at {model_filename}")
            return None

    def train_lr(self, X_train, y_train, X_val, y_val, model=None):
        # Use the provided model or create a new one if none is given
        if model is None:
            model = LinearRegression()
            model.fit(X_train, y_train)
        else:
            model.fit(X_train, y_train)

        # Prediction and evaluation
        y_pred = model.predict(X_val)
        mse = mean_squared_error(y_val, y_pred)
        mae = mean_absolute_error(y_val, y_pred)
        r2 = r2_score(y_val, y_pred)

        return model, mse, mae, r2

    def train_lstm(self, X_train, y_train, X_val, y_val):
        # Reshaping data for LSTM (samples, time steps, features)
        X_train = X_train.reshape((X_train.shape[0], 1, X_train.shape[1]))
        X_val = X_val.reshape((X_val.shape[0], 1, X_val.shape[1]))

        model = Sequential()
        model.add(LSTM(100, activation='relu', return_sequences=True, input_shape=(X_train.shape[1], X_train.shape[2])))
        model.add(Dropout(0.2))
        model.add(LSTM(50, activation='relu'))
        model.add(Dropout(0.2))
        model.add(Dense(1, activation='sigmoid'))

        optimizer = Adam(learning_rate=self.config["learning_rate"])
        model.compile(optimizer=optimizer, loss='binary_crossentropy', metrics=['accuracy'])

        early_stopping = EarlyStopping(monitor='val_loss', patience=10, restore_best_weights=True)
        
        model.fit(X_train, y_train, epochs=self.config["epochs"], batch_size=self.config["batch_size"], validation_data=(X_val, y_val), callbacks=[early_stopping], verbose=1)
        loss, accuracy = model.evaluate(X_val, y_val, verbose=0)
        
        return model, accuracy, loss

    def train_xgboost(self, X_train, y_train, X_val, y_val):
        model = xgb.XGBClassifier(
            use_label_encoder=False, 
            eval_metric='mlogloss', 
            max_depth=self.config["xgboost_max_depth"],
            learning_rate=self.config["learning_rate"],
            n_estimators=self.config["xgboost_n_estimators"]
        )
        model.fit(X_train, y_train)
        y_pred = model.predict(X_val)
        accuracy = accuracy_score(y_val, y_pred)
        
        return model, accuracy

    def train(self, model_type):
        # Preprocess the data
        X_train, X_val, X_test, y_train, y_val, y_test = self.preprocess_data()

        # Start an MLflow run
        with mlflow.start_run():
            # Check if we need to load an existing model
            if self.load_existing_model:
                model = self.load_model(model_type)
                if model is None:
                    logger.error(f"Failed to load existing model for {model_type}. Starting fresh training.")
                    model = None
            else:
                model = None

            # Train the selected model
            if model_type == 'lr':
                logger.info("Training Linear Regression model...")
                model, mse, mae, r2 = self.train_lr(X_train, y_train, X_val, y_val, model)
                mlflow.log_metric("MSE", mse)
                mlflow.log_metric("MAE", mae)
                mlflow.log_metric("R2", r2)
                mlflow.sklearn.log_model(model, "linear_regression")

            elif model_type == 'lstm':
                logger.info("Training LSTM model...")
                model, lstm_accuracy, lstm_loss = self.train_lstm(X_train, y_train, X_val, y_val)
                y_test_pred = model.predict(X_test)
                mse = mean_squared_error(y_test, y_test_pred)
                mae = mean_absolute_error(y_test, y_test_pred)
                r2 = r2_score(y_test, y_test_pred)
                
                mlflow.log_metric("accuracy", lstm_accuracy)
                mlflow.log_metric("loss", lstm_loss)
                mlflow.log_metric("MSE", mse)
                mlflow.log_metric("MAE", mae)
                mlflow.log_metric("R2", r2)
                mlflow.tensorflow.log_model(model, "lstm")

            elif model_type == 'xgboost':
                logger.info("Training XGBoost model...")
                model, xgboost_accuracy = self.train_xgboost(X_train, y_train, X_val, y_val)
                mlflow.log_metric("accuracy", xgboost_accuracy)
                mlflow.xgboost.log_model(model, "xgboost")

            logger.info(f"{model_type} model trained and logged with MLflow.")
            
            # Save the model to disk after training
            self.save_model(model, model_type)

def main():
    # Command line argument parsing
    parser = argparse.ArgumentParser(description="Train models using different algorithms and track using MLflow.")
    parser.add_argument("path", type=str, help="Path to the dataset CSV file.")
    parser.add_argument("--config", type=str, default="config.json", help="Path to the configuration JSON file.")
    parser.add_argument("--model", type=str, choices=['lr', 'lstm', 'xgboost'], help="The type of model to train.")
    parser.add_argument("--load_existing_model", action='store_true', help="Flag to load an existing model instead of retraining.")
    
    args = parser.parse_args()

    trainer = ModelTrainer(args.config, args.path, args.load_existing_model)
    trainer.train(args.model)

if __name__ == "__main__":
    main()

