"""为课程服务准备独立、固定版本的 DeepSeek Harness，不启动模型。"""
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from teacher_flow.common import RUNTIME, save

VERSION='0.1.5-rc.1'
INSTALL=RUNTIME.parent/'deepseek-harness'


def main():
    os.umask(0o077)
    package=INSTALL/'runtime/node_modules/@deepseek-ai/dsh'
    node=INSTALL/'runtime/bin/node'
    if not (package/'package.json').exists():
        root=INSTALL/'runtime'
        root.mkdir(parents=True,exist_ok=True)
        template=Path(__file__).resolve().parents[1]/'runtime/deepseek'
        for name in ('package.json','package-lock.json'):
            if (template/name).exists():shutil.copyfile(template/name,root/name)
        subprocess.run(['npm','ci' if (root/'package-lock.json').exists() else 'install',
                        '--no-audit','--no-fund'],cwd=root,check=True)
    if json.loads((package/'package.json').read_text())['version']!=VERSION:
        raise RuntimeError('课程制作运行时版本不符。')
    server=package/'node_modules/@deepseek-ai/dsh-sdk-jsonrpc-server/lib/index.js'
    source=server.read_text()
    before='const rec = { handle: await this.ctx.agents.create({\n\t\t\tsessionId: brandString(sessionId),'
    after=('// teacher-flow: connect the SDK to the native persisted-session resume API.\n'
           '\t\tconst opening = process.env.TEACHER_DSH_RESUME === sessionId\n'
           '\t\t\t? (options) => this.ctx.agents.resume({...options, resumeSessionId: options.sessionId})\n'
           '\t\t\t: (options) => this.ctx.agents.create(options);\n'
           '\t\tconst rec = { handle: await opening({\n\t\t\tsessionId: brandString(sessionId),')
    if before in source:
        if source.count(before)!=1:raise RuntimeError('SDK 会话入口与预期不一致。')
        server.write_text(source.replace(before,after))
    elif after not in source:raise RuntimeError('SDK 恢复入口需要核对。')
    source_node=INSTALL/'runtime/node_modules/node/bin/node'
    if not node.exists():
        node.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source_node,node)
    node_version=subprocess.check_output([str(node),'--version'],text=True).strip()
    if int(node_version.lstrip('v').split('.')[0])<24:raise RuntimeError('需要 Node 24 或以上版本。')
    save(INSTALL/'manifest.json',{'harness':'deepseek','version':VERSION,'node':node_version,
                                'package':str(package),'node_bin':str(node),'model_calls':0,
                                'resume_patch':'native-resume-v1','sdk_server_sha256':hashlib.sha256(server.read_bytes()).hexdigest()})
    print(json.dumps({'harness':'deepseek','version':VERSION,'node':node_version,'installed':True},ensure_ascii=False))


if __name__=='__main__':main()
