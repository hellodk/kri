# salt/states/jenkins_slave/init.sls
# Installs and configures a Jenkins build agent on macOS via a launchd plist.
# Requires pillar keys: jenkins_slave_secret, jenkins_url
# Optional pillar keys: jenkins_agent_name (defaults to minion ID), jenkins_agent_workdir

{% set jenkins_url = pillar.get('jenkins_url', 'http://jenkins:8080') %}
{% set jenkins_secret = pillar['jenkins_slave_secret'] %}
{% set agent_name = pillar.get('jenkins_agent_name', grains['id']) %}
{% set workdir = pillar.get('jenkins_agent_workdir', '/var/jenkins') %}
{% set plist_label = 'com.jenkins.slave' %}
{% set plist_path = '/Library/LaunchDaemons/' ~ plist_label ~ '.plist' %}

jenkins_agent_workdir:
  file.directory:
    - name: {{ workdir }}
    - makedirs: True
    - user: root
    - group: wheel
    - mode: '0755'

jenkins_agent_jar:
  file.managed:
    - name: /usr/local/bin/agent.jar
    - source: {{ jenkins_url }}/jnlpJars/agent.jar
    - skip_verify: True
    - makedirs: True

jenkins_slave_plist:
  file.managed:
    - name: {{ plist_path }}
    - source: salt://jenkins_slave/files/com.jenkins.slave.plist.jinja
    - template: jinja
    - context:
        jenkins_url: {{ jenkins_url }}
        jenkins_secret: {{ jenkins_secret }}
        agent_name: {{ agent_name }}
        workdir: {{ workdir }}
    - user: root
    - group: wheel
    - mode: '0644'

jenkins_slave_service:
  cmd.run:
    - name: launchctl load -w {{ plist_path }}
    - unless: launchctl list | grep -q {{ plist_label }}
    - require:
      - file: jenkins_slave_plist
      - file: jenkins_agent_jar
