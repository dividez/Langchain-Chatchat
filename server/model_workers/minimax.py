from server.model_workers.base import ApiModelWorker
from fastchat import conversation as conv
import sys
import json
import httpx
from pprint import pprint
from typing import List, Dict


class MiniMaxWorker(ApiModelWorker):
    BASE_URL = 'https://api.minimax.chat/v1/text/chatcompletion{pro}?GroupId={group_id}'

    def __init__(
        self,
        *,
        model_names: List[str] = ["minimax-api"],
        controller_addr: str,
        worker_addr: str,
        **kwargs,
    ):
        kwargs.update(model_names=model_names, controller_addr=controller_addr, worker_addr=worker_addr)
        kwargs.setdefault("context_len", 16384)
        super().__init__(**kwargs)

        # TODO: 确认模板是否需要修改
        self.conv = conv.Conversation(
            name=self.model_names[0],
            system_message="",
            messages=[],
            roles=["USER", "BOT"],
            sep="\n### ",
            stop_str="###",
        )

    def prompt_to_messages(self, prompt: str) -> List[Dict]:
        result = []
        user_start = self.conv.roles[0] + ":"
        bot_start = self.conv.roles[1] + ":"
        for msg in prompt.split(self.conv.sep)[1:-1]:
            if msg.startswith(user_start):
                result.append({"sender_type": "USER", "text": msg[len(user_start):].strip()})
            elif msg.startswith(bot_start):
                result.append({"sender_type": "BOT", "text": msg[len(bot_start)].strip()})
            else:
                raise RuntimeError(f"unknow role in msg: {msg}")
        return result

    def generate_stream_gate(self, params):
        # 按照官网推荐，直接调用abab 5.5模型
        # TODO: 支持历史消息，支持指定回复要求，支持指定用户名称、AI名称

        super().generate_stream_gate(params)
        config = self.get_config()
        group_id = config.get("group_id")
        api_key = config.get("api_key")

        pro = "_pro" if config.get("is_pro") else ""
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        data = {
            "model": "abab5.5-chat",
            "stream": True,
            "tokens_to_generate": 1024, # TODO: 1024为官网默认值
            "mask_sensitive_info": True,
            "messages": self.prompt_to_messages(params["prompt"]),
            "temperature": params.get("temperature"),
            "top_p": params.get("top_p"),
            "bot_setting": [],
        }
        print("request data sent to minimax:")
        pprint(data)
        response = httpx.stream("POST",
                                self.BASE_URL.format(pro=pro, group_id=group_id),
                                headers=headers,
                                json=data)
        with response as r:
            text = ""
            for e in r.iter_text():
                if e.startswith("data: "): # 真是优秀的返回
                    data = json.loads(e[6:])
                    if not data.get("usage"):
                        if choices := data.get("choices"):
                            chunk = choices[0].get("delta", "").strip()
                            if chunk:
                                print(chunk)
                                text += chunk
                                yield json.dumps({"error_code": 0, "text": text}, ensure_ascii=False).encode() + b"\0"
    
    def get_embeddings(self, params):
        # TODO: 支持embeddings
        print("embedding")
        print(params)


if __name__ == "__main__":
    import uvicorn
    from server.utils import MakeFastAPIOffline
    from fastchat.serve.model_worker import app

    worker = MiniMaxWorker(
        controller_addr="http://127.0.0.1:20001",
        worker_addr="http://127.0.0.1:20004",
    )
    sys.modules["fastchat.serve.model_worker"].worker = worker
    MakeFastAPIOffline(app)
    uvicorn.run(app, port=20003)