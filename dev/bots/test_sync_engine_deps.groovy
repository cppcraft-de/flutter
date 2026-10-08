// Offline Jenkins parameter/wiring regression checks; no stages are executed.
// Run from repository root with Groovy 2.4 (or Jenkins' groovy-all JAR).
def source = new File('Jenkinsfile.testing').text
def calls = []
def binding = new Binding([
    params: [WINDOWS_PYTHON: 'python'],
    error: { String message -> throw new IllegalArgumentException(message) },
    sh: { String command -> calls << command },
    bat: { String command -> calls << command },
    withEnv: { List entries, Closure body ->
        assert entries.contains('GIT_CONFIG_KEY_0=core.longpaths')
        body()
    },
])
def script = new GroovyShell(binding).parse(source)
assert script.engineDepsSyncMode(null) == 'auto'
assert script.engineDepsSyncMode(false) == 'auto' // First timer run, old checkbox.
assert script.engineDepsSyncMode(true) == 'true'
assert script.engineDepsSyncMode('false') == 'false' // New explicit choice.
assert script.engineDepsSyncMode('true') == 'true'
assert script.engineDepsSyncMode(' AUTO ') == 'auto'
try {
    script.engineDepsSyncMode('typo')
    assert false: 'Invalid mode must fail'
} catch (IllegalArgumentException expected) {
    assert expected.message.contains('SYNC_ENGINE_DEPS')
}
assert source.contains("choice(name: 'SYNC_ENGINE_DEPS', choices: ['auto', 'true', 'false']")
assert !source.contains('!params.SYNC_ENGINE_DEPS')
binding.params.SYNC_ENGINE_DEPS = false
script.bootstrapEngineDependenciesUnix(false)
script.bootstrapEngineDependenciesUnix(true)
script.bootstrapEngineDependenciesWindows()
assert calls == [
    'python3 dev/bots/sync_engine_deps.py --mode auto',
    'python3 dev/bots/sync_engine_deps.py --mode auto --web',
    'python dev/bots/sync_engine_deps.py --mode auto',
]
calls.clear()
binding.params.SYNC_ENGINE_DEPS = 'false'
script.bootstrapEngineDependenciesWindows()
assert calls == ['python dev/bots/sync_engine_deps.py --mode false']
println 'Dependency sync default, legacy migration, and platform wiring checks passed.'
