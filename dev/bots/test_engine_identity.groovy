// Offline Jenkins identity wiring checks; does not execute stages or Git.
def source = new File('Jenkinsfile.testing').text
def calls = []
def unix = false
def checkouts = []
def deletions = 0
def binding = new Binding([
    params: [WINDOWS_PYTHON: 'python', REQUIRE_RELEASE_TAG: false, RELEASE_BRANCH: 'stable'],
    env: [FRAMEWORK_REVISION: 'a' * 40, ENGINE_ID: 'b' * 40],
    scm: [branches: [[name: '*/wsc-main']], userRemoteConfigs: [[url: 'https://example.invalid/flutter.git']]],
    checkout: { Map request -> checkouts << request },
    deleteDir: { deletions++ },
    error: { String message -> throw new IllegalArgumentException(message) },
    isUnix: { unix },
    sh: { String command -> calls << command },
    bat: { String command -> calls << command },
])
def script = new GroovyShell(binding).parse(source)
script.selectEngineBuildBranch()
unix = true
script.selectEngineBuildBranch()
assert calls == ['git checkout -B flutter-wsc-candidate.ci HEAD'] * 2
calls.clear()
script.validateSdkArchive('macos')
unix = false
script.validateSdkArchive('windows')
assert calls.size() == 2
assert calls.every { it.contains('--engine-id ' + 'b' * 40) }
assert calls.every { it.contains('--revision ' + 'a' * 40) }
assert !source.contains('last_engine_commit')
assert !source.contains('--full-rebuild-publication')
assert source.contains('publishEngineArtifacts()')
// Release discovery may follow the branch; packaging must use the saved SHA.
script.checkoutFullSource(false)
assert checkouts.last().branches == binding.scm.branches
binding.scm.branches = [[name: '*/branch-moved-during-build']]
for (hostIsUnix in [false, true]) {
    unix = hostIsUnix
    script.checkoutSdkSource()
    assert checkouts.last().branches == [[name: 'a' * 40]]
    assert checkouts.last().extensions[0].shallow == false
}
assert deletions == 2
binding.env.FRAMEWORK_REVISION = null
try {
    script.checkoutSdkSource()
    assert false: 'Missing selected revision must not fall back to a moving branch'
} catch (IllegalArgumentException expected) {
    assert expected.message.contains('FRAMEWORK_REVISION')
}
assert checkouts.size() == 3
assert deletions == 2
println 'CI branch context, pinned SDK checkouts, packaged identity, and Maven verification wiring passed.'
