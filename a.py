from openai import OpenAI

client = OpenAI(
  base_url = "https://integrate.api.nvidia.com/v1",
  api_key = "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"
)

completion = client.chat.completions.create(
  model="meta/llama-3.2-3b-instruct",
  messages=[{"role":"user","content":""}],
  temperature=0.2,
  top_p=0.7,
  max_tokens=1024,
  stream=False
)

print(completion.choices[0].message)