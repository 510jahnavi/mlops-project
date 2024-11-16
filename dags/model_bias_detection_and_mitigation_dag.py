##### Here comes the dag scripts for adding dag scripts
from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime
import os
# Import required modules
import pandas as pd
import json
import pickle
import logging
# Import the provided methods
from dags.src.model_bias_detection_and_mitigation import load_pkl_files_from_directory, load_splits, save_model, upload_to_gcp, run_detection, run_mitigation
from dags.src.model_pipeline import download_model_artifacts
from model.scripts.data_loader import load_and_split_dataset, load_config


# Configure logger
logger = logging.getLogger("bias_detection_mitigation")
logger.setLevel(logging.INFO)

# Define constants
BASE_PATH_TEST_SPLIT = os.path.join(os.path.dirname(__file__), '../model/data/')
BASE_PATH_DATA = os.path.join(os.path.dirname(__file__), '../dataset/data/')
ANALYSIS_LOCAL_PATH = os.path.join(os.path.dirname(__file__),'src/reports')
GCP_BUCKET_NAME = "model_bias_results" 
# latest local model stored 



paths = {
            "train": os.path.join(BASE_PATH_TEST_SPLIT, "train_data.csv"),
            "test": os.path.join(BASE_PATH_TEST_SPLIT, "test_data.csv"),
            "sensitive_train": os.path.join(BASE_PATH_TEST_SPLIT, "sensitive_train.csv"),
            "sensitive_test": os.path.join(BASE_PATH_TEST_SPLIT, "sensitive_test.csv"),
            "dataset": os.path.join(BASE_PATH_DATA, "data_preprocess.csv"),
            "config": os.path.join(os.path.dirname(__file__), '../model/scripts/config.json'),
            "model": os.path.join(os.path.dirname(__file__), '../model/pickle/')
        }


# Default args for DAG
default_args = {
    'owner': 'airflow',
    'start_date': datetime(2024, 11, 15),
    'retries': 1,
}

# Define the DAG
with DAG(
    'bias_detection_and_mitigation',
    default_args=default_args,
    schedule_interval=None,
    catchup=False,
) as dag:
    
  

    def load_single_json_file(directory_path):
        """
        Finds and loads the single JSON file in the specified directory.

        Args:
            directory_path (str): Path to the directory.

        Returns:
            tuple: A tuple containing the file name and the loaded JSON data.
        """
        if not os.path.isdir(directory_path):
            raise FileNotFoundError(f"Directory not found: {directory_path}")

        # Get all files in the directory
        json_files = [f for f in os.listdir(directory_path) if f.endswith('.json')]

        if len(json_files) == 0:
            raise FileNotFoundError("No JSON file found in the directory.")
        elif len(json_files) > 1:
            raise ValueError("Multiple JSON files found in the directory. Expected only one.")

        # Load the single JSON file
        json_file_path = os.path.join(directory_path, json_files[0])
        with open(json_file_path, 'r') as file:
            data = json.load(file)

        return data



    
    def load_model(model_type):
        """Load the most recent trained model based on timestamp. This loads from local folder"""
        # List all files in the pickle folder
        model_files = [f for f in os.listdir(paths["model"]) if f.startswith(f"{model_type}_model")]
        
        if not model_files:
            logger.error(f"No models found for {model_type}.")
            return None
        
        # Sort the files by timestamp (filename format ensures correct sorting)
        model_files.sort(reverse=True)  # Most recent file first
        
        # Get the most recent model file
        most_recent_model_file = model_files[0]
        
        # Load the model from the most recent file
        model_filename = os.path.join(paths["model"], most_recent_model_file)
        with open(model_filename, 'rb') as f:
            model = pickle.load(f)
        
        #model = model_data["model"]
        #dataset_date = model_data["dataset_date"]
        logger.info(f"Model loaded from {model_filename}")
        return model

    def load_data_splits(**kwargs):
        """
        Task to load data splits.
        """
        logger.info("Loading data splits.")
        # paths = {
        #     "X_train": os.path.join(BASE_PATH, "X_train.csv"),
        #     "X_test": os.path.join(BASE_PATH, "X_test.csv"),
        #     "y_train": os.path.join(BASE_PATH, "y_train.csv"),
        #     "y_test": os.path.join(BASE_PATH, "y_test.csv"),
        #     "sensitive_train": os.path.join(BASE_PATH, "sensitive_train.csv"),
        #     "sensitive_test": os.path.join(BASE_PATH, "sensitive_test.csv"),
        # }
        # data = load_splits(
        #     paths["X_train"],
        #     paths["X_test"],
        #     paths["y_train"],
        #     paths["y_test"],
        #     paths["sensitive_train"],
        #     paths["sensitive_test"],
        # )
        # logger.info("Data splits loaded successfully.")
        # kwargs['ti'].xcom_push(key='data_splits', value=data)
        
        # config
        test_size, validation_size = load_config(paths["config"])

        # load data
        load_and_split_dataset(paths["dataset"], test_size, validation_size, save_locally=True)
        
        # load latest trained model
        model_type = download_model_artifacts()
        return model_type

    def perform_bias_detection(model_type):
        """
        Task to perform bias detection.
        """
        logger.info("Starting bias detection.")
        # ti = kwargs['ti']
        # data = ti.xcom_pull(key='data_splits', task_ids='load_data_splits')
        # X_test, y_test, sensitive_test = pd.read_csv(data[1], data[3], data[5]
        train_data = pd.read_csv(paths['train'])
        test_data = pd.read_csv(paths['test'])
        sensitive_test = pd.read_csv(paths['sensitive_test'])

        X_test = test_data.drop(columns=['value'])
        y_test = test_data['value']

        # Load model
        logger.info("Loading model from local storage")
        model = load_model(model_type)

        # Run detection
        bias_detection_folder = run_detection(X_test, y_test, sensitive_test, model, None, os.path.join(ANALYSIS_LOCAL_PATH,'bias_identification'))
        logger.info(f"Bias detection completed. Results stored in {bias_detection_folder}.")
        # ti.xcom_push(key='detection_folder', value=detection_folder)

        return bias_detection_folder

    def perform_bias_mitigation(bias_detection_folder, model_type):
        """
        Task to perform bias mitigation.
        """
        bias_identification_report_json = load_single_json_file(bias_detection_folder)
        before_mitigation_metric_frame = load_pkl_files_from_directory(bias_detection_folder)

        if bias_identification_report_json['bias_detected']:
            logger.info("Starting bias mitigation.")

            # loading train, test, sensitive feature splits
            train_data = pd.read_csv(paths['train'])
            test_data = pd.read_csv(paths['test'])
            sensitive_test = pd.read_csv(paths['sensitive_test'])
            sensitive_train = pd.read_csv(paths['sensitive_train'])

            X_train = train_data.drop(columns=['value'])
            y_train = train_data['value']
            X_test = test_data.drop(columns=['value'])
            y_test = test_data['value']

            # Load model
            logger.info("Loading model from local path")
            model = load_model(model_type)

            # Run mitigation
            bias_mitigation_folder, mitigated_model = run_mitigation(
                X_train, X_test, y_train, y_test, sensitive_train, sensitive_test, model, None,  os.path.join(ANALYSIS_LOCAL_PATH,'bias_mitigation')
            )

            # saving the mitigated_models
            save_model(mitigated_model,model_type,os.path.join(paths['model'],'mitigated_models'))

            bias_mitigation_folder = load_pkl_files_from_directory(bias_mitigation_folder)
            
            logger.info(f"Bias mitigation completed. Results stored in {bias_mitigation_folder}.")
        else:
            logger.info(f"Bias not found")

        return bias_detection_folder, bias_mitigation_folder

    def upload_results_to_gcp(bias_detection_folder, bias_mitigation_folder):
        """
        Task to upload results to GCP.
        """
        logger.info("Uploading results to GCP.")

        logger.info(f"Uploading detection results from {bias_detection_folder}.")
        upload_to_gcp(bias_detection_folder, "detection_results", GCP_BUCKET_NAME)

        logger.info(f"Uploading mitigation results from {bias_mitigation_folder}.")
        upload_to_gcp(bias_mitigation_folder, "mitigation_results", GCP_BUCKET_NAME)

        logger.info("Results uploaded successfully.")
    

    def proceed_to_serving(results_path_tuple):
        bias_detection_folder, bias_mitigation_folder = results_path_tuple
        if not bias_mitigation_folder:
            logger.info('No bias deteced and no mitigation is done. Model can be pushed to serving')
        else:
            before_mitigation_metric_frame_dict = load_pkl_files_from_directory(bias_detection_folder)
            after_mitigation_metric_frame_dict = load_pkl_files_from_directory(bias_mitigation_folder)

            bias_detection_metric_frame = None
            bias_mitigation_metric_frame = None

            for file_name, metric_frame in before_mitigation_metric_frame_dict.items():
                bias_detection_metric_frame = metric_frame
            
            for file_name, metric_frame in after_mitigation_metric_frame_dict.items():
                bias_mitigation_metric_frame = metric_frame

            bias_detection_overall_mae = round(bias_detection_metric_frame.overall['mae'],4)
            bias_mitigation_overall_mae = round(bias_mitigation_metric_frame.overall['mae'],4)

            if bias_mitigation_overall_mae < bias_detection_overall_mae:
                logger.info(f'Bias has been mitigated from {bias_detection_overall_mae} to {bias_mitigation_overall_mae}')
            elif bias_mitigation_overall_mae == bias_detection_overall_mae:
                logger.info(f'No significant chang in Bias')
            else:
                logger.warning(f'No change in Bias. Stop the Model from being served.')
        

    # Define tasks
    load_data_splits_task = PythonOperator(
        task_id='load_data_splits',
        python_callable=load_data_splits,
        provide_context=True
        
    )

    perform_bias_detection_task = PythonOperator(
        task_id='perform_bias_detection',
        python_callable=perform_bias_detection,
        provide_context=True,
        op_args=[load_data_splits_task.output]
    )

    perform_bias_mitigation_task = PythonOperator(
        task_id='perform_bias_mitigation',
        python_callable=perform_bias_mitigation,
        provide_context=True,
        op_args=[load_data_splits_task.output,perform_bias_detection_task.output]
    )

    upload_results_to_gcp_task = PythonOperator(
        task_id='upload_results_to_gcp',
        python_callable=upload_results_to_gcp,
        provide_context=True,
        op_args=[perform_bias_detection_task.output,perform_bias_mitigation_task.output]
    )

    proceed_to_serving_task = PythonOperator(
        task_id='proceed_to_serving',
        python_callable= proceed_to_serving, 
        provide_context = True,
    )

    # Define task dependencies
    load_data_splits_task >> perform_bias_detection_task >> perform_bias_mitigation_task >> upload_results_to_gcp_task >> proceed_to_serving_task
