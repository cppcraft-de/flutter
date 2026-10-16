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
        junit: { Map args -> assert !args.allowEmptyResults; events << 'junit' },
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
assert exercise([code: 1]).result == 'UNSTABLE'
assert exercise([code: 2]).result == 'FAILURE'
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
