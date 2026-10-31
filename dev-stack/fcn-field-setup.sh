#!/usr/bin/env bash
# fcn-field-setup — prepara la configurazione di un NODO DA CAMPO, in un comando.
#
#   ./fcn-field-setup.sh --orcid 0000-0002-1825-0097 --name "Nome Cognome"
#   ./fcn-field-setup.sh --orcid … --name … --node-name scavo-2027 --host scavo-mac.local
#
# Genera i segreti del nodo dove c'è ancora il valore di sviluppo, dichiara il
# nodo «da campo», ne fa gestore l'iD dato e scrive la lista degli accreditati
# del nodo. Non stampa segreti, non accende container. Poi: fcn-install.sh e
# fcn-up.sh, che vedono `EM_NODE_KIND=field` e usano il realm senza account
# dimostrativi e il volume di Keycloak (docker-compose.field.yml).
# Il perché, per intero: in testa a field_setup.py.
if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  awk 'NR==1{next} /^#/{sub(/^# ?/,"");print;next} /^[[:space:]]*$/{next} {exit}' "$0"; exit 0
fi
set -euo pipefail
cd "$(dirname "$0")"
exec python3 field_setup.py "$@"
