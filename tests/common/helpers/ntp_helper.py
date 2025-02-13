import pytest
import time
from contextlib import contextmanager
from tests.common.utilities import wait_until
from tests.common.helpers.assertions import pytest_assert


@contextmanager
def setup_ntp_context(ptfhost, duthost, ptf_use_ipv6):
    """setup ntp client and server"""
    ptfhost.lineinfile(path="/etc/ntp.conf", line="server 127.127.1.0 prefer")

    # restart ntp server
    ntp_en_res = ptfhost.service(name="ntp", state="restarted")

    pytest_assert(wait_until(120, 5, 0, check_ntp_status, ptfhost),
                  "NTP server was not started in PTF container {}; NTP service start result {}"
                  .format(ptfhost.hostname, ntp_en_res))

    # setup ntp on dut to sync with ntp server
    config_facts = duthost.config_facts(host=duthost.hostname, source="running")['ansible_facts']
    ntp_servers = config_facts.get('NTP_SERVER', {})
    for ntp_server in ntp_servers:
        duthost.command("config ntp del %s" % ntp_server)

    duthost.command("config ntp add %s" % (ptfhost.mgmt_ipv6 if ptf_use_ipv6 else ptfhost.mgmt_ip))

    yield

    # stop ntp server
    ptfhost.service(name="ntp", state="stopped")
    # reset ntp client configuration
    duthost.command("config ntp del %s" % (ptfhost.mgmt_ipv6 if ptf_use_ipv6 else ptfhost.mgmt_ip))
    for ntp_server in ntp_servers:
        duthost.command("config ntp add %s" % ntp_server)
    # The time jump leads to exception in lldp_syncd. The exception has been handled by lldp_syncd,
    # but it will leave error messages in syslog, which will cause subsequent test cases to fail.
    # So we need to wait for a while to make sure the error messages are flushed.
    # The default update interval of lldp_syncd is 10 seconds, so we wait for 20 seconds here.
    time.sleep(20)


@pytest.fixture(scope="function")
def setup_ntp_func(ptfhost, duthosts, rand_one_dut_hostname, ptf_use_ipv6):
    with setup_ntp_context(ptfhost, duthosts[rand_one_dut_hostname], ptf_use_ipv6) as result:
        yield result


def check_ntp_status(host):
    res = host.command("ntpstat", module_ignore_errors=True)
    if res['rc'] != 0:
        return False
    return True


def run_ntp(duthost):
    """ Verify that DUT is synchronized with configured NTP server """
    ntpsec_conf_stat = duthost.stat(path="/etc/ntpsec/ntp.conf")
    using_ntpsec = ntpsec_conf_stat["stat"]["exists"]

    duthost.service(name='ntp', state='stopped')
    if using_ntpsec:
        duthost.command("timeout 20 ntpd -gq -u ntpsec:ntpsec")
    else:
        ntp_uid = ":".join(duthost.command("getent passwd ntp")['stdout'].split(':')[2:4])
        duthost.command("timeout 20 ntpd -gq -u {}".format(ntp_uid))
    duthost.service(name='ntp', state='restarted')
    pytest_assert(wait_until(720, 10, 0, check_ntp_status, duthost),
                  "NTP not in sync")
