#!/bin/bash

# Alias: chat

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

LOG_FILE=${LOG_FILE:-/dev/null}

API_URL="${API_URL:-http://127.0.0.1:8080}"

MESSAGES=(
    "{\"role\":\"system\",\"content\":\"Today is $(date +"%Y-%m-%d").\nYou are a helpful assistant.\"}"
)

TOOLNAMES=()
TOOLS=()
for file in "${ROOT_DIR}/"*; do
    if [[ -f "${file}" ]] && [[ "${file}" =~ .*/chat_tool_.*\.sh ]]; then
        # shellcheck disable=SC1090
        source "${file}"
    fi
done

trim() {
    shopt -s extglob
    set -- "${1##+([[:space:]])}"
    printf "%s" "${1%%+([[:space:]])}"
}

trim_trailing() {
    shopt -s extglob
    printf "%s" "${1%%+([[:space:]])}"
}

format_messages() {
    if [[ "${#MESSAGES[@]}" -eq 0 ]]; then
        return
    fi
    printf "%s," "${MESSAGES[@]}"
}

if command -v gdate; then
    date() {
        gdate "$@"
    }
fi

MAX_COMPLETION_TOKENS="${MAX_COMPLETION_TOKENS:-"2048"}"
FREQUENCY_PENALTY="${FREQUENCY_PENALTY:-"null"}"
PRESENCE_PENALTY="${PRESENCE_PENALTY:-"null"}"
RESPONSE_FORMAT="${RESPONSE_FORMAT:-"text"}"
LOGPROBS="${LOGPROBS:-"null"}"
TOP_LOGPROBS="${TOP_LOGPROBS:-"null"}"
SEED="${SEED:-"null"}"
STOP="${STOP:-"null"}"
TEMP="${TEMP:-"null"}"
TOP_P="${TOP_P:-"null"}"
TOP_K="${TOP_K:-"null"}"
TOOLS_WITH="${TOOLS_WITH:-"false"}"
SYSTEM_PROMPT_WITH="${SYSTEM_PROMPT_WITH:-"true"}"

chat_completion() {
    PROMPT="$(trim_trailing "$1")"
    if [[ -z "${PROMPT}" ]]; then
        return
    fi
    if [[ "${PROMPT:0:1}" == "@" ]] && [[ -f "${PROMPT:1}" ]]; then
        while IFS= read -r LINE; do
            MESSAGES+=("${LINE}")
        done < <(jq -cr '.messages[]' "${PROMPT:1}")
        DATA="$(format_messages)"
        DATA="{\"messages\":[${DATA%?}]}"
    else
        DATA="{\"messages\":[$(format_messages){\"role\":\"user\",\"content\":\"${PROMPT}\"}]}"
        MESSAGES+=("{\"role\":\"user\",\"content\":\"$PROMPT\"}")
    fi
    while true; do
        DATA="$(echo -n "${DATA}" | jq -cr \
            --argjson max_completion_tokens "${MAX_COMPLETION_TOKENS}" \
            --argjson response_format "{\"type\":\"${RESPONSE_FORMAT}\"}" \
            '{
                n: 1,
                stream: true,
                stream_options: {include_usage: true},
                max_completion_tokens: $max_completion_tokens,
                response_format: $response_format,
              } * .')"
        if [[ "${FREQUENCY_PENALTY}" != "null" || "${PRESENCE_PENALTY}" != "null" ]]; then
            DATA="$(echo -n "${DATA}" | jq -cr \
                --argjson frequency_penalty "${FREQUENCY_PENALTY}" \
                --argjson presence_penalty "${PRESENCE_PENALTY}" \
                "${FREQUENCY_PENALTY}" \
                '{
                    frequency_penalty: $frequency_penalty,
                    presence_penalty: $presence_penalty
                } * .')"
        fi
        if [[ "${LOGPROBS}" == "true" ]]; then
            DATA="$(echo -n "${DATA}" | jq -cr \
                --argjson logprobs "${LOGPROBS}" \
                --argjson top_logprobs "${TOP_LOGPROBS}" \
                '{
                    logprobs: true,
                    top_logprobs: $top_logprobs
                } * .')"
        fi
        if [[ "${SEED}" != "null" ]]; then
            DATA="$(echo -n "${DATA}" | jq -cr \
                --argjson seed "${SEED}" \
                '{
                    seed: $seed
                } * .')"
        fi
        if [[ "${STOP}" != "null" ]]; then
            DATA="$(echo -n "${DATA}" | jq -cr \
                --argjson stop "${STOP}" \
                '{
                    stop: $stop
                } * .')"
        fi
        if [[ "${TEMP}" != "null" ]]; then
            DATA="$(echo -n "${DATA}" | jq -cr \
                --argjson temp "${TEMP}" \
                '{
                    temperature: $temp
                } * .')"
        fi
        if [[ "${TOP_P}" != "null" ]]; then
            DATA="$(echo -n "${DATA}" | jq -cr \
                --argjson top_p "${TOP_P}" \
                '{
                    top_p: $top_p
                } * .')"
        fi
        if [[ "${TOP_K}" != "null" ]]; then
            DATA="$(echo -n "${DATA}" | jq -cr \
                --argjson top_k "${TOP_K}" \
                '{
                    top_k: $top_k
                } * .')"
        fi
        if [[ "${TOOLS_WITH}" == "true" ]]; then
            DATA="$(echo -n "${DATA}" | jq -cr \
                --argjson tools "$(printf '%s\n' "${TOOLS[@]}" | jq -cs .)" \
                '{
                    tools: $tools,
                    parallel_tool_calls: false
                } * .')"
        fi
        echo "Q: ${DATA}" >>"${LOG_FILE}"
        echo "${DATA}" >/tmp/request.json

        TOOL_CALLS=''
        TOOL_RESULTS=()
        CONTENT=''
        PRE_CONTENT=''
        START_TIME=$(date +%s%3N)
        FIRST_TOKEN_RECEIVED_TIME=0

        while IFS= read -r LINE; do
            if ((FIRST_TOKEN_RECEIVED_TIME == 0)); then
                FIRST_TOKEN_RECEIVED_TIME=$(date +%s%3N)
            fi
            echo "A: ${LINE}" >>"${LOG_FILE}"
            if [[ ! "${LINE}" = data:* ]]; then
                if [[ "${LINE}" =~ error:.* ]]; then
                    LINE="${LINE:7}"
                    echo "Error: ${LINE}"
                fi
                continue
            fi
            if [[ "${LINE}" =~ data:\ \[DONE\].* ]]; then
                break
            fi
            LINE="${LINE:5}"
            DELTA_TOOL_CALLS="$(echo "${LINE}" | jq -cr '.choices[0].delta.tool_calls')"
            if [[ "${DELTA_TOOL_CALLS}" != "null" ]]; then
                if [[ -z "${TOOL_CALLS}" ]]; then
                    TOOL_CALLS="${DELTA_TOOL_CALLS}"
                else
                    # Merge tool_call by its index
                    while IFS= read -r NEW_TOOL_CALL; do
                        INDEX="$(echo "${NEW_TOOL_CALL}" | jq -cr '.index')"
                        if [[ -z "${INDEX}" || "${INDEX}" == "null" ]]; then
                            continue
                        fi
                        EXISTING_TOOL_CALL="$(echo "${TOOL_CALLS}" | jq -cr --argjson index "${INDEX}" '.[] | select(.index == $index)')"
                        if [[ -z "${EXISTING_TOOL_CALL}" ]]; then
                            TOOL_CALLS="$(jq -cr --argjson new_tool_call "${NEW_TOOL_CALL}" '. + [$new_tool_call]' <<<"${TOOL_CALLS}")"
                        else
                            # Append arguments if exists
                            NEW_ARGUMENTS="$(echo "${NEW_TOOL_CALL}" | jq -cr '.function.arguments // empty')"
                            if [[ -n "${NEW_ARGUMENTS}" ]]; then
                                EXISTING_ARGUMENTS="$(echo "${EXISTING_TOOL_CALL}" | jq -cr '.function.arguments // empty')"
                                if [[ -n "${EXISTING_ARGUMENTS}" ]]; then
                                    MERGED_ARGUMENTS="${EXISTING_ARGUMENTS}${NEW_ARGUMENTS}"
                                else
                                    MERGED_ARGUMENTS="${NEW_ARGUMENTS}"
                                fi
                            fi
                            if [[ -n "${MERGED_ARGUMENTS}" ]]; then
                                UPDATED_TOOL_CALL="$(jq -cr --arg merged_arguments "${MERGED_ARGUMENTS}" '.function.arguments = $merged_arguments' <<<"${EXISTING_TOOL_CALL}")"
                            else
                                UPDATED_TOOL_CALL="${EXISTING_TOOL_CALL}"
                            fi
                            TOOL_CALLS="$(jq -cr --argjson index "${INDEX}" --argjson updated_tool_call "${UPDATED_TOOL_CALL}" 'map(if .index == $index then $updated_tool_call else . end)' <<<"${TOOL_CALLS}")"
                        fi
                    done < <(jq -cr '.[]' <<<"${DELTA_TOOL_CALLS}")
                fi
            fi
            FINISH_REASON="$(echo "${LINE}" | jq -cr '.choices[0].finish_reason')"
            if [[ "${FINISH_REASON}" == "tool_calls" ]]; then
                while IFS= read -r TOOL_CALL; do
                    ID="$(echo "${TOOL_CALL}" | jq -cr '.id')"
                    FUNC_NAME="$(echo "${TOOL_CALL}" | jq -cr '.function.name')"
                    FUNC_ARGS="$(echo "${TOOL_CALL}" | jq -cr '.function.arguments')"
                    printf "\n🛠️: calling %s %s %s\r" "${FUNC_NAME}" "${FUNC_ARGS}" "${ID}"
                    RESULT=$("${FUNC_NAME}" "${FUNC_ARGS}" "${ID}")
                    printf "\n🛠️: %s\n" "${RESULT}"
                    TOOL_RESULTS+=("${RESULT}")
                done < <(jq -cr '.[]' <<<"${TOOL_CALLS}")
                TOOL_CALLS=''
            fi
            CONTENT_SEG="$(
                echo "${LINE}" | jq -cr '.choices[0].delta.reasoning_content // .choices[0].delta.content'
                echo -n "#"
            )"
            CONTENT_SEG="${CONTENT_SEG:0:${#CONTENT_SEG}-2}"
            if [[ "${CONTENT_SEG}" != "null" ]]; then
                if [[ "${PRE_CONTENT: -1}" == "\\" ]] && [[ "${CONTENT_SEG}" =~ ^b|n|r|t|\\|\'|\"$ ]]; then
                    printf "\b "
                    case "${CONTENT_SEG}" in
                    b) printf "\b\b" ;;
                    n) printf "\b\n" ;;
                    r) printf "\b\r" ;;
                    t) printf "\b\t" ;;
                    \\) printf "\b\\" ;;
                    \') printf "\b'" ;;
                    \") printf "\b\"" ;;
                    esac
                    CONTENT_SEG=""
                else
                    PRE_CONTENT="${CONTENT_SEG}"
                    printf "%s" "${CONTENT_SEG}"
                fi
                CONTENT+="${CONTENT_SEG}"
            fi
            if echo "${LINE}" | jq -e '.usage != null' >/dev/null; then
                ELAPSED=$(($(date +%s%3N) - START_TIME))
                USAGE="$(echo "${LINE}" | jq -cr '.usage')"
                USAGE_COMPLETION_TOKENS="$(echo "${USAGE}" | jq -cr '.completion_tokens')"
                USAGE_TOTAL_TOKENS="$(echo "${USAGE}" | jq -cr '.total_tokens')"
                LATC=$(((FIRST_TOKEN_RECEIVED_TIME - START_TIME + ELAPSED) / 1000))
                TPS=0
                if ((USAGE_TOTAL_TOKENS > 0 && ELAPSED > 0)); then
                    TPS=$(echo "scale=2; $USAGE_TOTAL_TOKENS * 1000 / $ELAPSED" | bc)
                fi
                TTFT=$((FIRST_TOKEN_RECEIVED_TIME - START_TIME))
                TPOT=0
                if ((USAGE_COMPLETION_TOKENS > 0)); then
                    TPOT=$(echo "scale=2; ${ELAPSED} / ${USAGE_COMPLETION_TOKENS}" | bc)
                fi
                printf "\n------------------------"
                printf "\n- Latency               (LATC) : %10.2fs   -" "${LATC}"
                printf "\n- Token Per Second      (TPS ) : %10.2f    -" "${TPS}"
                printf "\n- Time To First Token   (TTFT) : %10.2fms  -" "${TTFT}"
                printf "\n- Time Per Output Token (TPOT) : %10.2fms  -" "${TPOT}"
                printf "\n------------------------\n"
                break
            fi
        done < <(curl \
            --silent \
            --no-buffer \
            --request POST \
            --url "${API_URL}/v1/chat/completions" \
            --header "Content-Type: application/json" \
            --data @/tmp/request.json)

        printf "\n"

        if [[ -n "${TOOL_CALLS}" ]]; then
            MESSAGES+=("{\"role\":\"assistant\",\"content\":null,\"tool_calls\":$TOOL_CALLS}")
        fi
        if [[ -n "${CONTENT}" ]]; then
            MESSAGES+=("{\"role\":\"assistant\",\"content\":$(jq -Rs . <<<"${CONTENT}")}")
        fi
        if [[ "${#TOOL_RESULTS[@]}" -gt 0 ]]; then
            MESSAGES+=("${TOOL_RESULTS[@]}")
            DATA="{\"messages\":$(printf '%s\n' "${MESSAGES[@]}" | jq -cs .)}"
        else
            break
        fi
    done
}

if [[ "${TOOLS_WITH}" == "false" ]]; then
    TOOLNAMES=()
    TOOLS=()
fi

if [[ "${SYSTEM_PROMPT_WITH}" == "false" ]]; then
    MESSAGES=()
fi

echo "====================================================="
echo "LOG_FILE              : ${LOG_FILE}"
echo "API_URL               : ${API_URL}"
echo "MAX_COMPLETION_TOKENS : ${MAX_COMPLETION_TOKENS}"
echo "FREQUENCY_PENALTY     : ${FREQUENCY_PENALTY}"
echo "PRESENCE_PENALTY      : ${PRESENCE_PENALTY}"
echo "RESPONSE_FORMAT       : ${RESPONSE_FORMAT}"
echo "LOGPROBS              : ${LOGPROBS}"
echo "TOP_LOGPROBS          : ${TOP_LOGPROBS}"
echo "SEED                  : ${SEED}"
echo "STOP                  : ${STOP}"
echo "TEMP                  : ${TEMP}"
echo "TOP_P                 : ${TOP_P}"
echo "TOP_K                 : ${TOP_K}"
echo "TOOLS_WITH            : ${TOOLS_WITH}"
echo "TOOLS                 : $(printf '%s\n' "${TOOLNAMES[@]}" | jq -R . | jq -cs .)"
echo "SYSTEM_PROMPT_WITH    : ${SYSTEM_PROMPT_WITH}"
printf "=====================================================\n\n"

if [[ -f "${LOG_FILE}" ]]; then
    : >"${LOG_FILE}"
fi
if [[ ! -f "${LOG_FILE}" ]]; then
    touch "${LOG_FILE}"
fi

if [[ "${#@}" -ge 1 ]]; then
    echo "> ${*}"
    chat_completion "${*}"
else
    while true; do
        read -r -e -p "> " PROMPT
        if [[ "${PROMPT}" == "exit" || "${PROMPT}" == "quit" ]]; then
            break
        fi
        chat_completion "${PROMPT}"
    done
fi
