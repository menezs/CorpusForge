from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from typing import Optional, Type, Any, Dict, Union


class LLMService:
    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-ai/deepseek-v3.1",
        temperature: float = 0.7,
        provider: str = "openai",
        base_url: Optional[str] = None
    ):
        self._api_key = api_key
        self._model = model
        self._temperature = temperature
        self._provider = provider
        self._base_url = base_url
        self._client: Optional[Union[ChatOllama, ChatOpenAI]] = None

    @property
    def client(self) -> Union[ChatOllama, ChatOpenAI]:
        if self._client is None:
            if self._provider == "ollama":
                self._client = ChatOllama(
                    model=self._model,
                    temperature=self._temperature,
                    base_url=self._base_url
                )
            elif self._provider == "openai":
                self._client = ChatOpenAI(
                    model=self._model,
                    temperature=self._temperature,
                    base_url=self._base_url,
                    api_key=self._api_key or "dummy"
                )
            else:
                raise ValueError(f"Unknown provider: {self._provider}")
        return self._client

    def _get_client(self, temperature: Optional[float] = None) -> Union[ChatOllama, ChatOpenAI]:
        if temperature is not None:
            if self._provider == "ollama":
                return ChatOllama(
                    model=self._model,
                    temperature=temperature,
                    base_url=self._base_url
                )
            elif self._provider == "openai":
                return ChatOpenAI(
                    model=self._model,
                    temperature=temperature,
                    base_url=self._base_url,
                    api_key=self._api_key or "dummy"
                )
            else:
                raise ValueError(f"Unknown provider: {self._provider}")
        return self.client

    def complete(
        self,
        prompt: str,
        system_message: Optional[str] = None,
        temperature: Optional[float] = None
    ) -> str:
        messages = []
        if system_message:
            messages.append(SystemMessage(content=system_message))
        messages.append(HumanMessage(content=prompt))

        client = self._get_client(temperature)
        response = client.invoke(messages)
        return response.content

    def complete_json(
        self,
        prompt: str,
        system_message: Optional[str] = None,
        temperature: Optional[float] = None,
        schema: Optional[Type[Any]] = None
    ) -> Dict[str, Any]:
        parser = JsonOutputParser(pydantic_schema=schema) if schema else JsonOutputParser()
        
        format_instructions = parser.get_format_instructions()
        messages = []
        if system_message:
            messages.append(SystemMessage(content=system_message))
        messages.append(HumanMessage(content=f"{prompt}\n\n{format_instructions}"))

        client = self._get_client(temperature)
        response = client.invoke(messages)
        return parser.parse(response.content)