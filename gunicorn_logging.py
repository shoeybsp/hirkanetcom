import json, logging, os
from datetime import datetime, timezone
from gunicorn.glogging import Logger
class JsonAccessLogger(Logger):
    def access(self, resp, req, environ, request_time):
        if not self.access_log_enabled: return
        atoms=self.atoms(resp,req,environ,request_time)
        payload={
          "@timestamp":datetime.now(timezone.utc).isoformat(),"message":"HTTP access",
          "service":{"name":os.getenv("SERVICE_NAME","hirkanet")},
          "event":{"dataset":"hirkanet.gunicorn_access","category":"web","duration":int(request_time.total_seconds()*1_000_000_000)},
          "http":{"request":{"method":atoms.get("m")},"response":{"status_code":int(atoms.get("s",0)),"body":{"bytes":int(atoms.get("B",0) or 0)}}},
          "url":{"path":atoms.get("U")},"source":{"ip":atoms.get("h")},
          "user_agent":{"original":atoms.get("a")},"request":{"id":environ.get("HTTP_X_REQUEST_ID")}
        }
        self.access_log.info(json.dumps(payload,separators=(",",":")))
