from google.genai import types as gtypes
import inspect

print("FunctionResponse fields:")
print(gtypes.FunctionResponse.model_fields.keys())

print("\nFunctionResponse.__init__ signature:")
print(inspect.signature(gtypes.FunctionResponse.__init__))
