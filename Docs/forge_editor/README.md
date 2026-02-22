# Forge Editor — Cross-DCC Script IDE Prototype

Built for Maya, Blender, Unreal, Unity, and beyond.

## Quick Start

```bash
pip install PySide6
cd forge_editor
python main.py
```

## Architecture

```
forge_editor/
├── main.py                 # Entry point + dark theme setup
├── config/
│   └── settings.py         # Persistent settings (QSettings)
├── ui/
│   ├── main_window.py      # Main window with dual-mode UI
│   ├── code_editor.py      # Code editor (syntax HL, brace match, auto-indent)
│   ├── output_window.py    # Execution output with colored messages
│   ├── sidebar.py          # Workspace tree, code outline, open editors
│   └── ai_panel.py         # AI chat interface (BYOK + managed)
├── adapters/
│   ├── base_adapter.py     # Abstract DCC adapter interface
│   ├── maya_adapter.py     # Maya command port adapter
│   ├── blender_adapter.py  # Blender socket adapter
│   └── adapter_manager.py  # Multi-DCC connection manager
├── ai/                     # AI integration (MCP client, context injection)
├── plugins/
│   └── __init__.py         # Plugin system (discovery, loading, API)
└── resources/              # Icons, themes, etc.
```

## Two UI Modes

| Simple Mode (Default) | Advanced Mode |
|-|-|
| Tabs + Editor + Output | + Sidebar (workspace, outline, open editors) |
| Charcoal Editor 2 feel | + AI Panel |
| Perfect for quick scripts | + Project folder management |
| Toggle with button in toolbar | Full IDE experience |

## DCC Adapters

Each DCC connector implements `DCCAdapter`:
- `connect()` / `disconnect()` / `ping()`
- `execute(code, language)` — run code in the DCC
- `get_completions()` — auto-complete from live DCC
- `get_scene_info()` — context for AI injection
- `get_mcp_server_info()` — MCP integration

**Maya**: command port (TCP socket), MEL + Python
**Blender**: socket server addon, Python
**Unreal**: Python remote execution plugin (stub)
**Unity**: C# WebSocket bridge (stub)

## Key CE2 Features Implemented

- ✅ Syntax highlighting (Python, MEL)
- ✅ Line numbers with current line highlight
- ✅ Brace/bracket matching
- ✅ Auto-indent + smart indent (colon, braces)
- ✅ Auto-close brackets and quotes
- ✅ Matching word highlighting
- ✅ Toggle comment (Ctrl+/)
- ✅ Tab indent/unindent for selections
- ✅ Execute All / Selected / Line (never deletes code)
- ✅ Auto-save before execute
- ✅ Temporary buffers (persisted) + file buffers
- ✅ Movable, closeable tabs
- ✅ Code outline (classes, functions, methods, procs)
- ✅ Open editors panel
- ✅ Workspace / project folder tree
- ✅ Split editor + output with splitter
- ✅ Go to Line (Ctrl+G)
- ✅ Local Python execution fallback

## Plugin System

Third-party plugins extend Forge via `ForgePlugin`:

```python
class MyPlugin(ForgePlugin):
    name = "My Plugin"
    plugin_id = "com.example.myplugin"
    version = "1.0.0"
    
    def activate(self, api: ForgePluginAPI):
        api.add_toolbar_action("My Button", self.do_thing)
    
    def deactivate(self):
        pass
```

Plugins can: register DCC adapters, add panels, add menus, execute in DCCs, interact with AI layer.

## AI Integration

- **BYOK**: Anthropic (Claude), OpenAI (GPT), Local (Ollama/LM Studio), Custom endpoint
- **Managed**: Forge Pro AI subscription (future)
- **MCP**: Connect to existing DCC MCP servers for scene manipulation
- **Context injection**: Current code, output/errors, DCC scene state sent to AI

## Business Model

| Tier | Price | Features |
|-|-|-|
| Free/Demo | $0 | Limited tabs, no workspaces |
| Standard | $99-149 perpetual | Full editor, all adapters, BYOK AI |
| Pro AI | +$15-25/mo | Tuned prompts, recipes, agent workflows |
| Studio | Custom | Volume licensing, on-prem AI |

## Next Steps

- [ ] Find/Replace dialog (local + global)
- [ ] Code folding
- [ ] Auto-complete popup
- [ ] Split view (drag tab to edge)
- [ ] Unreal + Unity adapter stubs
- [ ] MCP client integration
- [ ] Shelf/hotkey integration for Maya
- [ ] Workspace save/load
- [ ] Theme customization
- [ ] Git integration panel
