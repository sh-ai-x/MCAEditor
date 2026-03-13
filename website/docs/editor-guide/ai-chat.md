# AI Chat (Orange Slice)

Orange Slice is MCA Editor's built-in AI assistant. It understands your code, your scene, and your editor state — and can take actions directly in Maya.

---

## Opening AI Chat

Click the **Orange Slice** icon on the right tool stripe, or find it under **Plugins > Orange Slice**.

The chat panel opens on the right side of the editor.

---

## What It Can Do

Orange Slice has access to 16 tools that let it interact with your editor and Maya:

- **Read and write files** in your project
- **Execute Python and MEL** code in Maya
- **Navigate** to files and lines in the editor
- **Read your current code** and selection
- **Query editor state** — open files, cursor position, project info, DCC connection

This means you can ask it things like:

- *"Select all meshes in the scene and print their vertex counts"*
- *"Write a script that renames all joints with a prefix"*
- *"What does this selected code do?"*
- *"Create a new file called utils.py with a function to..."*

---

## Setup

Orange Slice supports three AI providers. You bring your own API key:

| Provider | Model | Setup |
|---|---|---|
| Anthropic | Claude Sonnet | API key from [console.anthropic.com](https://console.anthropic.com) |
| OpenAI | GPT-4o | API key from [platform.openai.com](https://platform.openai.com) |
| Google | Gemini Flash | API key from [aistudio.google.com](https://aistudio.google.com) |

To configure:

1. Open the AI Chat panel
2. Click the **gear icon** to open settings
3. Select your provider
4. Enter your API key
5. Optionally change the model

Your API key is stored locally in your settings and is never sent anywhere except the provider's API.

---

## Tips

- **Be specific** — "Create a script that selects all meshes with more than 10,000 triangles" works better than "help me with meshes"
- **Use context** — Select code in the editor before asking about it, so Orange Slice can see your selection
- **Let it execute** — Orange Slice can run code in Maya directly, so let it test its own scripts
