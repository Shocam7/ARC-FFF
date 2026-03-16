from google.genai import types as gtypes
import inspect

print("FunctionResponse fields:")
print(gtypes.FunctionResponse.model_fields.keys())

if hasattr(gtypes, 'FunctionResponsePart'):
    print("\nFunctionResponsePart fields:")
    print(gtypes.FunctionResponsePart.model_fields.keys())
else:
    print("\nFunctionResponsePart NOT found.")

print("\nPart fields:")
print(gtypes.Part.model_fields.keys())
