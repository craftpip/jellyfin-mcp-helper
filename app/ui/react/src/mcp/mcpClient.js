const MCP_URL = '/mcp'

export async function mcpCall(name, args = {}) {
  const body = {
    jsonrpc: '2.0',
    method: 'tools/call',
    id: Date.now(),
    params: { name, arguments: args },
  }
  const res = await fetch(MCP_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const json = await res.json()
  if (json.error) throw new Error(json.error.message || 'MCP error')
  const text = json.result?.content?.[0]?.text
  if (text) return JSON.parse(text)
  return json.result || {}
}

export async function mcpListTools() {
  const body = { jsonrpc: '2.0', method: 'tools/list', id: Date.now() }
  const res = await fetch(MCP_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const json = await res.json()
  if (json.error) throw new Error(json.error.message || 'MCP error')
  return json.result?.tools || []
}
