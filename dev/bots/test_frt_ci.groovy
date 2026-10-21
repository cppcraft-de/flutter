// Offline Pipeline wiring tests. No Jenkins, builds, downloads or rendering.
def source = new File('Jenkinsfile.testing').text

class TestAbort extends RuntimeException {}

def exercise = { Map options ->
    def events = []
    def build = [currentResult: options.initial ?: 'SUCCESS']
    def worsen = { String result ->
        if (['SUCCESS', 'UNSTABLE', 'FAILURE', 'ABORTED'].indexOf(result) >
            ['SUCCESS', 'UNSTABLE', 'FAILURE', 'ABORTED'].indexOf(build.currentResult)) {
            build.currentResult = result
        }
    }
    def plan = [hosts: ['windows', 'macos'], repository: 'https://example.invalid/frt.git']
    def binding = new Binding([
        env: [WSC_FRT_REPORT_READY: options.disabled ? null : 'true',
              WSC_FRT_REVISION: 'a' * 40, BUILD_NUMBER: '123'],
        params: [WINDOWS_PYTHON: 'python'], currentBuild: build,
        scm: [userRemoteConfigs: [[credentialsId: 'test-id']]],
        echo: { String text -> events << 'echo' },
        timeout: { Map args, Closure body -> body() },
        node: { String label, Closure body -> assert label == 'flutter_win'; events << 'node'; body() },
        pwd: { Map args -> assert args.tmp; 'scratch' },
        dir: { String path, Closure body -> events << "dir:${path}".toString(); body() },
        deleteDir: { events << 'clean-report-scratch' },
        readFile: { String path -> '{}' },
        readJSON: { Map args -> assert args.returnPojo; plan },
        checkout: { Map args ->
            assert args.scm.branches == [[name: 'a' * 40]]
            assert !args.poll
            events << 'checkout-pinned-frt'
        },
        unstash: { String name ->
            events << "unstash:${name}".toString()
            if (options.abort && name == 'frt-windows') { throw new TestAbort() }
            if (options.missing && name == 'frt-macos') { throw new IOException('No stash') }
        },
        catchError: { Map args, Closure body ->
            assert !args.catchInterruptions
            try { body() }
            catch (TestAbort e) { throw e }
            catch (Exception e) { worsen('FAILURE') }
        },
        bat: { Map args ->
            assert args.returnStatus
            assert args.script.contains('frt_ci.py report')
            events << 'report'
            options.code ?: 0
        },
        archiveArtifacts: { Map args -> events << 'archive' },
        fileExists: { String path -> !(options.noXml && path.endsWith('.xml')) },
        junit: { Map args ->
            assert args.testResults == 'artifacts/frt-junit.xml'
            assert !args.allowEmptyResults
            events << 'junit'
        },
        unstable: { String text -> worsen('UNSTABLE') },
        error: { String text -> worsen('FAILURE'); throw new IllegalArgumentException(text) },
    ])
    def script = new GroovyShell(binding).parse(source)
    try { script.aggregateFrt() }
    catch (IllegalArgumentException expected) { events << 'failed' }
    catch (TestAbort expected) { events << 'aborted'; worsen('ABORTED') }
    [events: events, result: build.currentResult]
}

def pass = exercise([:])
assert pass.result == 'SUCCESS'
assert pass.events.indexOf('archive') < pass.events.indexOf('junit')
assert pass.events.contains('checkout-pinned-frt')
def mismatch = exercise([code: 1])
assert mismatch.result == 'UNSTABLE' && mismatch.events.contains('junit')
def executionError = exercise([code: 2])
assert executionError.result == 'FAILURE' && executionError.events.contains('junit')
assert exercise([code: 17]).result == 'FAILURE'
assert exercise([initial: 'FAILURE', code: 1]).result == 'FAILURE'
def missing = exercise([missing: true])
assert missing.result == 'FAILURE'
assert missing.events.containsAll(['report', 'archive', 'junit'])
def noXml = exercise([noXml: true])
assert noXml.result == 'FAILURE'
assert noXml.events.contains('archive') && !noXml.events.contains('junit')
assert !exercise([disabled: true]).events.contains('node')
assert !exercise([initial: 'ABORTED']).events.contains('node')
def abort = exercise([abort: true])
assert abort.result == 'ABORTED' && !abort.events.contains('report')
// Reports only: no SDKs, databases, or old broad evidence archive.
assert source.contains("stash name: \"frt-\${host}\"")
assert !source.contains('frt_ci.py archive')
assert source.contains('script { aggregateFrt() }')
assert source.contains('results/comparison/comparison.html')
assert source.contains('results/*/comparison/comparison.html')
println 'FRT aggregation, missing inputs, publication, status precedence and abort wiring passed.'

// Execute capture failure paths and check which files the real archive patterns select.
def captureFailure = { boolean missingStash, boolean aborted ->
    def archived = []
    def output = 'build/frt-results/windows-123'
    def files = [
        "${output}/runner.log",
        "${output}/results/windows/baseline-build.log",
        "${output}/results/web/specimen-build.log",
        "${output}/results/windows/comparison/baseline-client.log",
        "${output}/results/web/comparison/specimen-client.log",
        "${output}/results/web/comparison/server.log",
        "${output}/results/web/comparison/regression.sqlite3",
        "${output}/results/windows/specimen-client/app.exe",
        "${output}/results/windows/specimen-client/nested-build.log",
    ].collect { it.toString() }
    def binding = new Binding([
        env: [WSC_FRT_PLAN: 'plan', WSC_FRT_REVISION: 'a' * 40, BUILD_NUMBER: '123'],
        params: [WINDOWS_PYTHON: 'python'],
        scm: [userRemoteConfigs: [[credentialsId: 'test-id']]],
        readJSON: { Map args -> args.text == 'plan'
            ? [enabled: true, repository: 'https://example.invalid/frt.git']
            : [exit_code: 2, status: 'error'] },
        isUnix: { false },
        timeout: { Map args, Closure body -> body() },
        dir: { String path, Closure body -> body() },
        checkout: { Map args -> },
        writeFile: { Map args -> },
        bat: { Map args -> if (aborted) { throw new TestAbort() }; 2 },
        readFile: { String path -> 'result' },
        fileExists: { String path -> true },
        error: { String message -> throw new IllegalArgumentException(message) },
        catchError: { Map args, Closure body ->
            assert !args.catchInterruptions
            try { body() }
            catch (TestAbort e) { throw e }
            catch (Exception expected) { }
        },
        stash: { Map args -> if (missingStash) { throw new IOException('Missing report') } },
        archiveArtifacts: { Map args ->
            def patterns = args.artifacts.split(',')
            archived.addAll(files.findAll { path -> patterns.any { pattern ->
                // DirectoryScanner normalizes separators before matching.
                org.apache.tools.ant.types.selectors.SelectorUtils.matchPath(
                    pattern.replace('/', File.separator), path.replace('/', File.separator))
            } })
        },
    ])
    try {
        new GroovyShell(binding).parse(source).runFrt('windows')
        assert false: 'Capture failure must still fail'
    } catch (TestAbort expected) {
        assert aborted
    } catch (IllegalArgumentException expected) {
        assert !aborted
    }
    assert archived == files.take(6)
}
captureFailure(false, false)
captureFailure(true, false)
captureFailure(true, true)
println 'FRT partial build/client/server logs survive capture errors, missing reports and cancellation; bundles stay excluded.'
