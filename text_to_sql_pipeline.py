"""
title: Llama Index DB Pipeline
author: 0xThresh
date: 2024-08-11
version: 1.1
license: MIT
description: A pipeline for using text-to-SQL for retrieving relevant information from a database using the Llama Index library.
requirements: llama_index, sqlalchemy, psycopg2-binary
"""

from typing import List, Union, Generator, Iterator
import os 
from pydantic import BaseModel
from llama_index.llms.ollama import Ollama
from llama_index.core.query_engine import NLSQLTableQueryEngine
from llama_index.core import SQLDatabase, PromptTemplate
from sqlalchemy import create_engine


class Pipeline:
    class Valves(BaseModel):
        DB_HOST: str
        DB_PORT: str
        DB_USER: str
        DB_PASSWORD: str        
        DB_DATABASE: str
        DB_TABLE: str
        OLLAMA_HOST: str
        TEXT_TO_SQL_MODEL: str 


    # Update valves/ environment variables based on your selected database 
    def __init__(self):
        self.name = "Database RAG Pipeline"
        self.engine = None
        self.nlsql_response = ""

        # Initialize
        self.valves = self.Valves(
            **{
                "pipelines": ["*"],                                                           # Connect to all pipelines
                "DB_HOST": os.getenv("DB_HOST", "http://host.docker.internal"),                     # Database hostname
                "DB_PORT": os.getenv("DB_PORT", "5432"),                                        # Database port 
                "DB_USER": os.getenv("DB_USER", "postgres"),                                  # User to connect to the database with
                "DB_PASSWORD": os.getenv("DB_PASSWORD", "qwer5678"),                          # Password to connect to the database with
                "DB_DATABASE": os.getenv("DB_DATABASE", "testdb"),                          # Database to select on the DB instance
                "DB_TABLE": os.getenv("DB_TABLE", "actor"),                            # Table(s) to run queries against 
                "OLLAMA_HOST": os.getenv("OLLAMA_HOST", "http://host.docker.internal:11434"), # Make sure to update with the URL of your Ollama host, such as http://localhost:11434 or remote server address
                "TEXT_TO_SQL_MODEL": os.getenv("TEXT_TO_SQL_MODEL", "llama2:latest")            # Model to use for text-to-SQL generation      
            }
        )

    def init_db_connection(self):
        # Update your DB connection string based on selected DB engine - current connection string is for Postgres
        self.engine = create_engine(f"postgresql+psycopg2://{self.valves.DB_USER}:{self.valves.DB_PASSWORD}@{self.valves.DB_HOST}:5432/{self.valves.DB_DATABASE}")
        return self.engine

    async def on_startup(self):
        # This function is called when the server is started.
        self.init_db_connection()

    async def on_shutdown(self):
        # This function is called when the server is stopped.
        pass

    def pipe(
        self, user_message: str, model_id: str, messages: List[dict], body: dict
    ) -> Union[str, Generator, Iterator]:
        # Debug logging is required to see what SQL query is generated by the LlamaIndex library; enable on Pipelines server if needed

        # Create database reader for Postgres
        sql_database = SQLDatabase(self.engine, include_tables=[self.valves.DB_TABLE])

        # Set up LLM connection; uses phi3 model with 128k context limit since some queries have returned 20k+ tokens
        llm = Ollama(model=self.valves.TEXT_TO_SQL_MODEL, base_url=self.valves.OLLAMA_HOST, request_timeout=180.0, context_window=30000)

        # Set up the custom prompt used when generating SQL queries from text
        text_to_sql_prompt = """
        Given an input question, first create a syntactically correct {dialect} query to run, then look at the results of the query and return the answer. 
        You can order the results by a relevant column to return the most interesting examples in the database.
        Unless the user specifies in the question a specific number of examples to obtain, query for at most 5 results using the LIMIT clause as per Postgres. You can order the results to return the most informative data in the database.
        Never query for all the columns from a specific table, only ask for a few relevant columns given the question.
        You should use DISTINCT statements and avoid returning duplicates wherever possible.
        Pay attention to use only the column names that you can see in the schema description. Be careful to not query for columns that do not exist. Pay attention to which column is in which table. Also, qualify column names with the table name when needed. You are required to use the following format, each taking one line:


        Question: Question here
        SQLQuery: SQL Query to run
        SQLResult: Result of the SQLQuery
        Answer: Final answer here

        Only use tables listed below.
        {schema}

        Question: {query_str}
        SQLQuery: 
        """

        text_to_sql_template = PromptTemplate(text_to_sql_prompt)

        query_engine = NLSQLTableQueryEngine(
            sql_database=sql_database, 
            tables=[self.valves.DB_TABLE],
            llm=llm, 
            embed_model="local", 
            text_to_sql_prompt=text_to_sql_template, 
            streaming=True
        )

        response = query_engine.query(user_message)

        return response.response_gen