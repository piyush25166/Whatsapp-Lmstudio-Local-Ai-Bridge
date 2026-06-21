from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)

# Point the OpenAI client to your local LM Studio server
client = OpenAI(base_url="http://127.0.0.1:1234/v1", api_key="lm-studio")

@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    user_message = data.get('message', '')
    sender = data.get('sender', 'unknown')
    
    print(f"Incoming message from {sender}: {user_message}")

    try:
        # Pipeline the message to LM Studio
        response = client.chat.completions.create(
            model="local-model", # LM Studio intercepts this automatically
            messages=[
                {"role": "system", "content": "You are a helpful, concise WhatsApp bot."},
                {"role": "user", "content": user_message}
            ],
            temperature=0.7
        )
        
        ai_reply = response.choices[0].message.content
        return jsonify({"reply": ai_reply})
        
    except Exception as e:
        print(f"Error querying LM Studio: {e}")
        return jsonify({"reply": "Sorry, my AI brain is currently offline."}), 500

if __name__ == '__main__':
    # Start the Python server on port 5000
    app.run(port=5000)