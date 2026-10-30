[LUNA - <u>L</u>earning How Young <u>U</u>sers <u>N</u>avigate When <u>A</u>ccessing Online Information](https://anonymous.4open.science/r/child-search-logger/)

This repository accompanies the demo paper submission "LUNA - <u>L</u>earning How Young <u>U</u>sers <u>N</u>avigate When <u>A</u>ccessing Online Information" for CHIIR 2027. It contains the full setup of LUNA used for a use case pertaining to children's information seeking in the classroom. This enables others to either reproduce our results or adapt the platform for their own study.

## Structure of this Repository

* `logger/search-app/`: Contains code and static files for the front end of the search platform
* `logger/search-engine/`: Contains the code for search engine implementation

## VertexAI API
For our use case, we leveraged the VertexAI API for retrieval and ranking. Follow the instructions [here](https://docs.cloud.google.com/generative-ai-app-builder/docs/website-search-checklist?indexing=basic) to set up your own instance of Vertex AI search.

### Important details 
* Remove `.example` from the environment files in `logger/search-app`

* In Setp 1. Set up a Google Cloud project, store the `project number` under the `GOOGLE_CLOUD_PROJECT` variable in the environment files, and under `project_number` variable in `logger/search-app/API_keys.json`.

* After setting up a Google cloud service account under Step 1, replace the dummy file `logger/search-app/service_account.json` with your private `service_account.json` file.

* In Step 3. Create a data store, you will have to provide a list of URLs for indexing. Please use .txt files in `logger/search-app/corpus/` to reproduce our datastores for topics India and Space. Assign the India topic datastore ID to `GOOGLE_DATASTORE_ID` variable in `logger/search-app/vertex-india.env`, and Space topic datastore ID to `GOOGLE_DATASTORE_ID` variable in `logger/search-app/vertex-space.env`.

* In Step 4. Create your app, choose `Custom search (general)` as your type of Search app. Note that, like the datastores, we created two separate search apps for India and Space topics. Assign the app ID for India topic to `GOOGLE_ENGINE_ID` variable in `logger/search-app/vertex-india.env` and the app ID for Space topic to `GOOGLE_ENGINE_ID` variable in `logger/search-app/vertex-space.env`, respectively.

* If reproducing study for grade 3, use assign the India topic datastore and app IDs to `data_store_id` and `engine_id` variables, respectively in `logger/search-app/API_keys.json`; for grade 4, assign the Space topic datastore and app IDs to the corresponding variables.

* Step 6 and 7, use all default settings.

## SERP API
We used [SERP API](https://serpapi.com/) for generating query autocomplete suggestions. [Generate you private API Key](https://serpapi.com/manage-api-key) and assign the API key value to `api_key` variable in `logger/search-app/API_keys.json`.

## Local deployment using Docker
Run the following commands on your terminal from inside the `logger/` folder

1. Run docker-compose.yml
```
bash
docker-compose up --build
```
2. After building the docker images you can access the fronted via:
```
bash
http://[Enter Server-IP Address here]:7001/
```