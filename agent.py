"""
Business logic for AI agent with knowledge base integration, 
cross-region reranking, and source attribution.
"""
import os
import boto3
from dotenv import load_dotenv
from llama_index.retrievers.bedrock import AmazonKnowledgeBasesRetriever
from llama_index.llms.openai import OpenAI
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.tools import QueryEngineTool
from llama_index.core.agent.workflow import ReActAgent
from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.postprocessor.bedrock_rerank import BedrockRerank

load_dotenv()

# 1. RERANKER: Amazon Rerank 1.0 located in Oregon (us-west-2)
reranker = BedrockRerank(
    model_id="amazon.rerank-v1:0", 
    top_n=3,
    region_name="us-west-2" 
)

# 2. RETRIEVER: Knowledge Base located in Ohio (us-east-2)
retriever = AmazonKnowledgeBasesRetriever(
    knowledge_base_id=os.getenv("BEDROCK_KNOWLEDGE_BASE_ID"),
    retrieval_config={
        "vectorSearchConfiguration": {
            "numberOfResults": 10,  
            "overrideSearchType": "HYBRID" 
        }
    },
    region_name="us-east-2" 
)

# 3. LLM: OpenAI GPT model
llm = OpenAI(model=os.getenv("OPENAI_MODEL"))

# 4. KNOWLEDGE BASE TOOL: Combining Retriever + Reranker
query_engine = RetrieverQueryEngine.from_args(
    retriever=retriever,
    node_postprocessors=[reranker]
)

_knowledge_base_tool = QueryEngineTool.from_defaults(
    query_engine=query_engine,
    name="msk_knowledge_base",
    description=(
        "Search for specific financial data, trust documents, and MSK company policies."
    ),
)


agent = ReActAgent(
    tools=[_knowledge_base_tool],
    llm=llm,
    system_prompt=(
    "You are a Senior Wealth Management Strategy Partner at MSK Wealth Management. "
    "Your primary goal is to minimize advisor meeting prep time by synthesizing complex client data into high-impact, 'meeting-ready' briefs. "
    
    "## YOUR OPERATING PRINCIPLES:\n"
    "1. **Analysis Over Description**: Do not just repeat data. Explain *why* it matters for the client's current life stage (e.g., 'The $5M liquidity event in Document X triggers a significant tax exposure under 2026 Ontario statutes').\n"
    "2. **Rule-Based Rigor**: Always cross-reference client actions against the provided 'Rules, Regulations, and Policies' knowledge base. Highlight any compliance red flags or missing legal triggers.\n"
    "3. **Advisor-First Perspective**: Focus on 'Actionable Insights.' If a deadline is approaching (like the DLT tax trigger), place it at the top of the response.\n"
    "4. **Concise Professionalism**: Use executive summaries, bullet points, and Markdown tables. Avoid filler language and reasoning thoughts in the final output.\n"
    
    "## RESPONSE STRUCTURE:\n"
    "- **Executive Brief**: A 2-sentence summary of the client's current status.\n"
    "- **Critical Deadlines & Compliance**: Any urgent regulatory or policy-driven actions.\n"
    "- **Financial Analysis Table**: A high-level view of assets, liabilities, or tax codes found in the records.\n"
    "- **Recommended Meeting Talking Points**: 3 specific questions the advisor should ask the client based on the gaps you found."
    )
)


bedrock_agent_client = boto3.client('bedrock-agent', region_name='us-east-2')

def trigger_sync():
    """Triggers the Bedrock Knowledge Base Ingestion Job."""
    try:
        response = bedrock_agent_client.start_ingestion_job(
            knowledgeBaseId=os.getenv("BEDROCK_KNOWLEDGE_BASE_ID"),
            dataSourceId=os.getenv("BEDROCK_DATA_SOURCE_ID")
        )
        return response['ingestionJob']['ingestionJobId'], response['ingestionJob']['status']
    except Exception as e:
        return None, str(e)

def get_sync_status(job_id):
    """Checks the status of a specific ingestion job."""
    try:
        response = bedrock_agent_client.get_ingestion_job(
            knowledgeBaseId=os.getenv("BEDROCK_KNOWLEDGE_BASE_ID"),
            dataSourceId=os.getenv("BEDROCK_DATA_SOURCE_ID"),
            ingestionJobId=job_id
        )
        return response['ingestionJob']['status']
    except Exception as e:
        return str(e)

def format_sources(source_nodes):
    """Format source nodes into readable citation text."""
    if not source_nodes:
        return ""
    
    sources = []
    seen_sources = set()
    
    for node in source_nodes:
        # Extract S3 URI from metadata
        s3_uri = node.node.metadata.get('sourceMetadata', {}).get('x-amz-bedrock-kb-source-uri', '')
        
        if s3_uri and s3_uri not in seen_sources:
            # Extract just the filename from S3 path
            filename = s3_uri.split('/')[-1]
            page_num = node.node.metadata.get('sourceMetadata', {}).get('x-amz-bedrock-kb-document-page-number', '')
            
            if page_num:
                sources.append(f"📄 {filename} (Page {int(page_num)})")
            else:
                sources.append(f"📄 {filename}")
            
            seen_sources.add(s3_uri)
    
    if sources:
        return "\n\n**Sources:**\n" + "\n".join(sources)
    return ""

# 7. MAIN STREAMING RESPONSE LOGIC
async def get_agent_response(message, chat_history):
    """Get agent response with source attribution."""
    try:
        messages = [
            ChatMessage(
                role=MessageRole.USER if msg["role"] == "user" else MessageRole.ASSISTANT,
                content=msg["content"]
            )
            for msg in chat_history
        ]
        
        user_message = ChatMessage(role=MessageRole.USER, content=message)
        
        # Get response from agent
        response = await agent.run(user_message, chat_history=messages)
        
        # Query engine directly to get sources
        engine_response = query_engine.query(message)
        sources_text = format_sources(engine_response.source_nodes) if hasattr(engine_response, 'source_nodes') else ""
        
        return str(response) + sources_text
        
    except Exception as e:
        return f"I apologize, but I encountered an error: {str(e)}"
