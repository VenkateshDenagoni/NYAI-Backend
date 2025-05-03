import nltk
import os
import logging

logger = logging.getLogger("nyai.nltk_setup")

def download_nltk_data():
    """Download required NLTK data packages if they don't exist."""
    try:
        # Create NLTK data directory in a location the container user has write access to
        nltk_data_dir = os.path.join(os.path.expanduser("~"), "nltk_data")
        os.makedirs(nltk_data_dir, exist_ok=True)
        
        # Set NLTK data path
        nltk.data.path.append(nltk_data_dir)
        
        # List of required NLTK resources
        required_resources = [
            ('tokenizers/punkt', 'punkt'),
            ('corpora/stopwords', 'stopwords'),
            ('corpora/wordnet', 'wordnet'),
        ]
        
        # Download missing resources
        for resource_path, resource_name in required_resources:
            try:
                nltk.data.find(resource_path)
                logger.info(f"NLTK resource '{resource_name}' already exists")
            except LookupError:
                logger.info(f"Downloading NLTK resource '{resource_name}'")
                nltk.download(resource_name, download_dir=nltk_data_dir)
                
        logger.info("NLTK setup completed successfully")
        return True
    except Exception as e:
        logger.error(f"Error setting up NLTK: {str(e)}")
        # Don't fail the application if NLTK setup fails
        return False 