# LabOps monitoring plugins

These are standalone **Monitoring Plugins API-compatible** checks. They use the
same command-line contract consumed by Nagios, Icinga and related monitoring
systems:

- exit `0` = OK
- exit `1` = WARNING
- exit `2` = CRITICAL
- exit `3` = UNKNOWN
- first-line status text on stdout
- performance data after `|` using the standard
  `'label'=value;warn;crit;min;max` form
- explicit network timeouts and warning/critical latency thresholds

The repository does **not** install or claim operation of a Nagios or Icinga
server. The evidence here is for custom plugin development, deployment and
execution. A monitoring daemon can consume these checks later without changing
their result contract.

## Checks

### NATS / JetStream

Runs on the private broker because the NATS monitoring listener stays on
loopback:

~~~bash
/usr/local/libexec/labops-monitoring/check_labops_nats.py \
  --url 'http://127.0.0.1:8222/healthz?js-enabled-only=true' \
  --warning-ms 250 --critical-ms 1000
~~~

Example:

~~~text
OK - JetStream health ok in 4.8 ms | 'latency'=4.8ms;250;1000;0
~~~

### Go event-worker systemd unit

~~~bash
/usr/local/libexec/labops-monitoring/check_labops_systemd.py \
  --unit labops-event-worker
~~~

Example:

~~~text
OK - labops-event-worker is active | 'active'=1;;;0;1
~~~

### End-to-end Flask / PostgreSQL health

On the AWS web host this checks the same loopback Nginx route used by the
operator-facing health verification:

~~~bash
/usr/local/libexec/labops-monitoring/check_labops_http.py \
  --url http://127.0.0.1/health \
  --warning-ms 500 --critical-ms 2000
~~~

A 200 response is not enough: the JSON must also report `status=ok`,
`db=connected` and `db_result=1`.

## Nagios command examples

~~~text
define command {
    command_name    check_labops_nats
    command_line    /usr/local/libexec/labops-monitoring/check_labops_nats.py -w $ARG1$ -c $ARG2$
}

define command {
    command_name    check_labops_worker
    command_line    /usr/local/libexec/labops-monitoring/check_labops_systemd.py -U labops-event-worker
}

define command {
    command_name    check_labops_http
    command_line    /usr/local/libexec/labops-monitoring/check_labops_http.py -u http://127.0.0.1/health -w $ARG1$ -c $ARG2$
}
~~~

## Icinga 2 command examples

~~~icinga2
object CheckCommand "labops-nats" {
  command = [ "/usr/local/libexec/labops-monitoring/check_labops_nats.py" ]
  arguments = {
    "-w" = "$labops_warning_ms$"
    "-c" = "$labops_critical_ms$"
  }
}

object CheckCommand "labops-worker" {
  command = [ "/usr/local/libexec/labops-monitoring/check_labops_systemd.py" ]
  arguments = {
    "-U" = "labops-event-worker"
  }
}

object CheckCommand "labops-http" {
  command = [ "/usr/local/libexec/labops-monitoring/check_labops_http.py" ]
  arguments = {
    "-u" = "http://127.0.0.1/health"
    "-w" = "$labops_warning_ms$"
    "-c" = "$labops_critical_ms$"
  }
}
~~~

Those snippets are integration examples only; this lab does not claim a
configured Nagios/Icinga scheduler, agent, notification path or production
alert-routing deployment.
