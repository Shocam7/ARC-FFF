from google import genai

def list_all_models():
    # Ensure you have your key set or passed here
    client = genai.Client(api_key="AIzaSyD0pam9wPz1EFb3Da_tAaOUqOQSdnu9Cj8")

    print(f"{'Model Name':<45} | {'Actions'}")
    print("-" * 80)

    try:
        # We remove the 'if' filter to see EVERY model your key has access to
        for model in client.models.list():
            actions = ", ".join(model.supported_actions)
            print(f"{model.name:<45} | {actions}")
                
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    list_all_models()