import logging
import pydantic
import json

from typing import Union, Dict, Any, Tuple, Optional, Callable

from .utils import filter_nonjsonable_keys, is_jsonable

RawDataType = Union[Dict[str, Any], pydantic.BaseModel]

logger = logging.getLogger(__name__)


def convert_to_dict(x: Any) -> Dict[str, object]:
    """Convert objects to a dict, ideally json serializable."""
    if isinstance(x, dict):
        return x
    elif isinstance(x, pydantic.BaseModel):
        return x.model_dump()
    elif isinstance(x, str):
        # Probably a str representation of json
        return json.loads(x)
    elif isinstance(x, bytes):
        # Probably a byte representation of json
        return json.loads(x.decode())
    else:
        try:
            return dict(x)
        except ValueError as e:
            raise ValueError(f"Could not convert to dict: {x}. Error: {e}")
        except TypeError as e:
            raise NotImplementedError(
                f"Dict conversion not implemented for type {type(x)}: {x}"
            )


def detect_str_from_input(input: RawDataType) -> str:
    """
    This function extracts from an arbitrary input the string representation, aka the prompt.
    """
    # OpenAI inputs: Look for messages list
    if (
        isinstance(input, dict)
        and ("messages" in input.keys())
        and isinstance(input["messages"], list)
        and (len(input["messages"]) > 0)
        and ("content" in input["messages"][-1])
    ):
        content = input["messages"][-1].get("content", None)
        if content is not None:
            return str(content)

    # Unimplemented. Translate everything to str
    return str(input)


# def detect_task_id_and_to_log_from_output(
#     output: RawDataType
# ) -> Tuple[Optional[str], Optional[bool]]:
#     """
#     This function extracts from an arbitrary output an eventual task_id and to_log bool.
#     task_id is used to grouped multiple outputs together.
#     to_log is used to delay the call to the phospho API. Only logs marked as to_log will
#     be recorded to phospho.
#     This is useful to fully receive a streamed response before logging it to phospho.
#     """
#     output_class_name = output.__class__.__name__
#     output_module = output.__class__.__module__
#     logger.debug(
#         f"Detecting task_id from output class_name:{output_class_name} ; module:{output_module}"
#     )

#     # OpenAI Stream API
#     # task_id = ChatCompletionMessage.id
#     # finish_reason = ChatCompletionMessage.choices[0].finish_reason
#     if isinstance(output, pydantic.BaseModel) and (
#         output_class_name == "ChatCompletionChunk"
#     ):
#         task_id = getattr(output, "id", None)
#         choices = getattr(output, "choices", None)
#         if isinstance(choices, list) and len(choices) > 0:
#             # finish_reason is a str if completion has finished
#             finish_reason = getattr(choices[0], "finish_reason", None)

#         return task_id, (finish_reason is not None)
#     # Unimplemented
#     return None, None


def detect_str_from_output(output: RawDataType) -> str:
    """
    This function extracts from an arbitrary output its string representation.
    For example, from an OpenAI's ChatCompletion, extract the message displayed to the
    end user.
    """
    output_class_name = output.__class__.__name__
    output_module = output.__class__.__module__
    logger.debug(
        f"Detecting str from output class_name:{output_class_name} ; module:{output_module}"
    )

    # If streaming and receiving bytes
    if isinstance(output, bytes):
        try:
            # Assume it may be a json
            output = convert_to_dict(output)
        except Exception as e:
            logger.warning(
                f"Error while trying to convert output {type(output)} to dict"
            )

    # OpenAI outputs
    if isinstance(output, pydantic.BaseModel):
        if output_class_name in ["ChatCompletion", "ChatCompletionChunk"]:
            choices = getattr(output, "choices", None)
            if isinstance(choices, list) and len(choices) > 0:
                if output_class_name == "ChatCompletion":
                    # output = ChatCompletionMessage.choices[0].message.content
                    message = getattr(choices[0], "message", None)
                    content = getattr(message, "content", None)
                    if content is not None:
                        return str(content)
                elif output_class_name == "ChatCompletionChunk":
                    # new_token = ChatCompletionMessage.choices[0].delta.content
                    choice_delta = getattr(choices[0], "delta")
                    content = getattr(choice_delta, "content", None)
                    if content is not None:
                        return str(content)
                    else:
                        # None content = end of generation stream
                        return ""

    if isinstance(output, dict):
        # OpenAI outputs
        if "choices" in output.keys():
            choices = output["choices"]
            if isinstance(choices, list) and len(choices) > 0:
                # output = ChatCompletionMessage.choices[0].message.content
                message = choices[0].get("message", None)
                if message is not None:
                    # ChatCompletion
                    content = message.get("content", None)
                    if content is not None:
                        return str(content)
                else:
                    # ChatCompletionChunk (streaming)
                    choice_delta = choices[0].get("delta", {})
                    content = choice_delta.get("content", None)
                    if content is not None:
                        return str(content)
                    else:
                        # None content = end of generation stream
                        return ""

        # Ollama outputs
        if "response" in output.keys():
            return output["response"]

    # Unimplemented. Translate everything to str
    return str(output)


def detect_usage_from_input_output(
    input: Any, output: Any
) -> Optional[Dict[str, float]]:
    """
    Returns a dict with keys `prompt_tokens`, `completion_tokens`, `total_tokens`.
    """
    # OpenAI-like API return the usage in the output
    if isinstance(output, pydantic.BaseModel):
        output = output.model_dump()
    if isinstance(output, dict):
        if "usage" in output.keys():
            return output["usage"]
        if output.get("object", None) == "chat.completion.chunk":
            # When streaming, we generate token by token
            return {"completion_tokens": 1}
    return None


def detect_model_from_input_output(input: Any, output: Any) -> Optional[str]:
    """
    Returns the model used to generate the output.
    """
    # OpenAI-like API return the model in the output
    if isinstance(output, dict):
        if "model" in output.keys():
            return output["model"]
    if isinstance(input, dict):
        if "model" in input.keys():
            return input["model"]
    return None


def extract_data_from_output(
    output: Optional[Union[RawDataType, str]] = None,
    raw_output: Optional[RawDataType] = None,
    output_to_str_function: Optional[Callable[[Any], str]] = None,
) -> Tuple[
    Optional[str],
    Optional[Union[Dict[str, object], str]],
]:
    """
    Convert any supported data type to standard, loggable inputs and outputs.

    :param output:
        The output content to be logged. Can be a string, a dict, a Pydantic model, or None.

    :param raw_output:
        Will be separately logged in raw_output_to_log if specified.

    :param output_to_str_function:


    :return:
    - output_to_log _(Optional[str])_ -
        A string representation of the output, or None if no output is specified.

    - raw_output_to_log _(Optional[Dict[str, object]])_ -
        A dict representation of the output, raw_output if specified, or None if output is a str.

    """

    # Default functions to extract string from input and output
    if output_to_str_function is None:
        output_to_str_function = detect_str_from_output

    raw_output_to_log: Optional[Union[Dict[str, object], str]] = None

    if output is not None:
        # Extract a string representation from output
        if isinstance(output, str):
            output_to_log = output
            raw_output_to_log = output
        else:
            output_to_log = output_to_str_function(output)
            if not is_jsonable(output):
                raw_output_to_log = filter_nonjsonable_keys(convert_to_dict(output))
            else:
                raw_output_to_log = output
    else:
        output_to_log = None

    # If raw output is specified, override
    if raw_output is not None:
        if not is_jsonable(raw_output):
            raw_output_to_log = filter_nonjsonable_keys(convert_to_dict(raw_output))
        else:
            raw_output_to_log = raw_output

    return (
        output_to_log,
        raw_output_to_log,
    )


def extract_data_from_input(
    input: Union[RawDataType, str],
    raw_input: Optional[RawDataType] = None,
    input_to_str_function: Optional[Callable[[Any], str]] = None,
) -> Tuple[
    str,
    Optional[Union[Dict[str, object], str]],
]:
    """
    Convert any supported data type to standard, loggable inputs.

    :param input:
        The input content to be logged. Can be a string, a dict, or a Pydantic model.

    :param raw_input:
        Will be separately logged in raw_input_to_log if specified.

    :param input_to_str_function:


    :return:
    - input_to_log _(str)_ -
        A string representation of the input.

    - raw_input_to_log _(Optional[Dict[str, object]])_ -
        A dict representation of the input, raw_input if specified, or None if input is a str.

    """

    # Default functions to extract string from input and output
    if input_to_str_function is None:
        input_to_str_function = detect_str_from_input

    raw_input_to_log: Optional[Union[Dict[str, object], str]] = None

    # Extract a string representation from input
    if isinstance(input, str):
        input_to_log = input
        raw_input_to_log = input
    else:
        # Extract input str representation from input
        input_to_log = input_to_str_function(input)
        if not is_jsonable(input):
            raw_input_to_log = filter_nonjsonable_keys(convert_to_dict(input))
        else:
            raw_input_to_log = input

    # If raw input is specified, override
    if raw_input is not None:
        if not is_jsonable(raw_input):
            raw_input_to_log = filter_nonjsonable_keys(convert_to_dict(raw_input))
        else:
            raw_input_to_log = raw_input

    return (
        input_to_log,
        raw_input_to_log,
    )


def extract_metadata_from_input_output(
    input: Union[RawDataType, str],
    output: Optional[Union[RawDataType, str]] = None,
    input_output_to_usage_function: Optional[
        Callable[[Any, Any], Dict[str, float]]
    ] = None,
) -> Dict[str, object]:
    """
    Extract metadata from input and output:

    - usage (Optional[Dict[str, float]])
        A dict with keys `prompt_tokens`, `completion_tokens`, `total_tokens`.
    - model (Optional[str])
        The model used to generate the output.
    """
    metadata: Dict[str, object] = {}

    if input_output_to_usage_function is None:
        usage = detect_usage_from_input_output(input, output)

    else:
        usage = input_output_to_usage_function(input, output)
    if usage is not None:
        metadata.update(usage)

    model = detect_model_from_input_output(input, output)
    if model is not None:
        metadata.update({"model": model})

    return metadata
