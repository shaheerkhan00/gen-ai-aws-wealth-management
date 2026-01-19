import gradio as gr
import asyncio
import os
from dotenv import load_dotenv
from agent import get_agent_response, trigger_sync, get_sync_status

load_dotenv()

def create_gradio_interface():
    with gr.Blocks(title="MSK Wealth Management AI", css=".gradio-container {max-width: 900px; margin: auto;}") as demo:
        gr.Markdown("# 🏦 MSK Wealth Management AI Portal")
        
        with gr.Tabs():
            # TAB 1: Chat Interface
            with gr.Tab("💬 Client Advisor Chat"):
                history = gr.Chatbot(elem_id="chatbot", type='messages', height=500)
                msg = gr.Textbox(
                    placeholder="Ask about Jane Smith's portfolio or MSK policies...", 
                    container=False, 
                    scale=7
                )
                
                with gr.Row():
                    submit_btn = gr.Button("Send", variant="primary")
                    clear = gr.ClearButton([msg, history], value="Clear Chat")

            # TAB 2: Knowledge Base Admin
            with gr.Tab("⚙️ Knowledge Base Admin"):
                gr.Markdown("### Sync AI Memory with S3")
                gr.Info("Click below after uploading new PDFs to your S3 bucket (s3://msk-gen-ai-bucket).")
                sync_btn = gr.Button("🔄 Sync Knowledge Base", variant="secondary")
                status_output = gr.Textbox(label="Job Status", interactive=False)
            
        # Logic for Sync Flow
        async def run_sync_flow():
            job_id, initial_status = trigger_sync()
            if not job_id:
                yield f"❌ Error: {initial_status}"
                return
            
            current_status = initial_status
            while current_status not in ["COMPLETE", "FAILED", "STOPPED"]:
                current_status = get_sync_status(job_id)
                yield f"⏳ Job {job_id}: {current_status}..."
                await asyncio.sleep(3)
            
            if current_status == "COMPLETE":
                yield f"✅ Sync Successful! The AI is now updated with the latest documents."
            else:
                yield f"❌ Sync Ended with status: {current_status}"

        # STEP 1: Add user message immediately (NOT a generator)
        def add_user_message(message, chat_history):
            """Immediately add user message and clear input"""
            if not message.strip():
                return chat_history, message
            
            chat_history.append({"role": "user", "content": message})
            return chat_history, ""  # Return updated history and clear input

        # STEP 2: Get agent response with loading indicator (generator)
        async def get_bot_response(chat_history):
            """Get agent response and update chat"""
            if not chat_history or chat_history[-1]["role"] != "user":
                yield chat_history
                return  # Empty return is OK in generator
            
            user_message = chat_history[-1]["content"]
            
            # Add a loading message
            chat_history.append({"role": "assistant", "content": "🤔 Searching knowledge base..."})
            yield chat_history
            
            # Get the actual response
            response = await get_agent_response(user_message, chat_history[:-2])  # Exclude user msg and loading msg
            
            # Replace loading message with actual response
            chat_history[-1] = {"role": "assistant", "content": response}
            yield chat_history

        # Event Listeners
        sync_btn.click(run_sync_flow, outputs=status_output)

        # Event handling with progressive updates
        submit_btn.click(
            add_user_message,
            inputs=[msg, history],
            outputs=[history, msg]
        ).then(
            get_bot_response,
            inputs=[history],
            outputs=[history]
        )
        
        msg.submit(
            add_user_message,
            inputs=[msg, history],
            outputs=[history, msg]
        ).then(
            get_bot_response,
            inputs=[history],
            outputs=[history]
        )

    return demo

if __name__ == "__main__":
    app = create_gradio_interface()
    app.launch(
        server_name="0.0.0.0",
        server_port=8080,
        share=False
    )