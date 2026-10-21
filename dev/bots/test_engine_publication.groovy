// Offline publication wiring checks. No Jenkins, credentials or uploads.
def source = new File('Jenkinsfile.testing').text
def calls = []
def activeLock = false
def activeCredentials = false
def unix = true
def parameters = [UPLOAD_TRANSPORT: 'http_put', WINDOWS_PYTHON: 'python',
                  DANGEROUSLY_OVERWRITE_BUILD_ARTIFACTS: false]
def shell = { String command ->
    assert activeLock && activeCredentials
    calls << command
}
def binding = new Binding([
    params: parameters, env: [ENGINE_ID: 'a' * 40],
    isUnix: { unix }, sh: shell, bat: shell,
    error: { String message -> throw new IllegalArgumentException(message) },
    string: { Map value -> value },
    lock: { Map args, Closure body ->
        assert args.resource == 'wsc-engine-artifact-publication'
        activeLock = true
        try { body() } finally { activeLock = false }
    },
    withCredentials: { List args, Closure body ->
        assert args[0].variable == 'HTTP_UPLOAD_KEY'
        activeCredentials = true
        try { body() } finally { activeCredentials = false }
    },
])
def script = new GroovyShell(binding).parse(source)
assert script.artifactBaseUrl() == 'https://fluttertest.b-cdn.net/ci-v2'
assert script.uploadBaseUrl() == 'https://storage.bunnycdn.com/fluttertest/ci-v2'
binding.env.WSC_ARTIFACT_BASE_URL = 'http://local.invalid:8765'
binding.env.WSC_HTTP_UPLOAD_BASE_URL = 'http://local.invalid:8765'
assert script.artifactBaseUrl() == 'http://local.invalid:8765'
assert script.uploadBaseUrl() == 'http://local.invalid:8765'
parameters.ARTIFACT_BASE_URL = 'https://explicit.invalid/read'
parameters.HTTP_UPLOAD_BASE_URL = 'https://explicit.invalid/write'
assert script.artifactBaseUrl() == parameters.ARTIFACT_BASE_URL
assert script.uploadBaseUrl() == parameters.HTTP_UPLOAD_BASE_URL
script.publishEngineArtifacts()
assert calls.last().contains('publish_engine_artifacts.py')
assert !calls.last().contains('--dangerously-overwrite')
unix = false
parameters.DANGEROUSLY_OVERWRITE_BUILD_ARTIFACTS = true
script.publishEngineArtifacts()
assert calls.last().contains('--dangerously-overwrite')
assert !calls.last().contains("'")
assert !calls.last().contains('delete')
parameters.UPLOAD_TRANSPORT = 'sftp'
try {
    script.publishEngineArtifacts()
    assert false: 'Unsupported transport must not bypass protection'
} catch (IllegalArgumentException expected) {
    assert expected.message.contains('HTTP PUT')
}
assert calls.size() == 2
assert source.contains("name: 'DANGEROUSLY_OVERWRITE_BUILD_ARTIFACTS', defaultValue: false")
assert !source.contains("publishArtifactTree('build/artifact-payload')")
println 'Engine publication lock, credentials, default safety and overwrite wiring passed.'

// The same lock must span the seed origin check and upload, including no-op runs.
parameters.UPLOAD_TRANSPORT = 'http_put'
def hasSeeds = true
def lockCount = 0
binding.setVariable('lock', { Map args, Closure body ->
    assert args.resource == 'wsc-engine-artifact-publication'
    assert !activeLock
    lockCount++
    activeLock = true
    try { body() } finally { activeLock = false }
})
binding.setVariable('dir', { String path, Closure body ->
    assert activeLock && path == 'build/seed-payload'
    body()
})
binding.setVariable('deleteDir', { assert activeLock })
binding.setVariable('powershell', { Map args -> assert activeLock; hasSeeds ? 'yes' : '' })
binding.setVariable('bat', { String command ->
    assert activeLock
    if (command.contains('--verify-only')) {
        assert !activeCredentials
    } else {
        assert activeCredentials
    }
    calls << command
})
calls.clear()
script.seedArtifactMirror(['windows'] as Set)
assert lockCount == 1 && !activeLock && !activeCredentials
assert calls.size() == 3
assert calls[0].contains('--upload-base-url "https://explicit.invalid/write"')
assert calls[1].contains('upload_artifact_tree.py')
assert calls[2].contains('--verify-only')
hasSeeds = false
calls.clear()
script.seedArtifactMirror(['windows'] as Set)
assert lockCount == 2 && calls.size() == 2
assert !calls.any { it.contains('upload_artifact_tree.py') }
println 'Seed origin checks, uploads and verification share the publication lock.'
