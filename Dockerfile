FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies required for psycopg2 (PostgreSQL adapter)
# and potentially other libraries.
# gcc and libpq-dev are needed to build psycopg2 from source if a wheel isn't available.
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    # Add any other system dependencies here
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container
COPY requirements.txt .

# Install Python dependencies
# --no-cache-dir: Disables the cache to reduce image size
# --compile: Compiles Python source files to bytecode
RUN pip install --no-cache-dir --compile -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Command to run the application using Uvicorn
# --host 0.0.0.0 makes the server accessible externally (from other Docker containers or the host machine)
# --port 8000 is the port the application will listen on
# --reload is useful for development but should typically be removed for production images
# For this hackathon setup, --reload can be kept if frequent code changes are expected by participants
# directly modifying the container's code (though usually they'd rebuild).
# Let's remove --reload for a more "production-like" dummy app.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]