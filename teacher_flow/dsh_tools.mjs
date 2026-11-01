// 将现有课程工具注册到 DeepSeek Harness 的原生工具目录。
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const {defineTool} = await import(pathToFileURL(path.join(process.env.TEACHER_DSH_MODULES,
  '@deepseek-ai/dsh-tools/lib/index.js')).href);
export const name = 'teacher-course-tools';
export const inject = ['tools', 'attachments'];

function property(schema, required) {
  const value = {...schema};
  delete value.required;
  if(required===true) value.required=true;
  if(schema.type==='object') {
    value.properties = Object.fromEntries(Object.entries(schema.properties || {}).map(
      ([key, item])=>[key,property(item,(schema.required || []).includes(key))]));
  }
  if(schema.items) value.items=property(schema.items);
  return value;
}

export async function apply(ctx) {
  const base=process.env.TEACHER_DSH_TOOL_URL;
  const headers={Authorization:'Bearer '+process.env.TEACHER_DSH_TOOL_TOKEN,'Content-Type':'application/json'};
  const result=await fetch(base+'/tools',{headers});
  if(!result.ok) throw new Error('课程工具未就绪');
  const definitions=await result.json();
  for(const tool of definitions) {
    const schema=tool.inputSchema;
    ctx.tools.register(defineTool({
      name:tool.name, description:tool.description,
      parameters:Object.fromEntries(Object.entries(schema.properties || {}).map(
        ([key,item])=>[key,property(item,(schema.required || []).includes(key))])),
      output:{schema:{type:'json'},render:(_args,value)=>value.content},
      async execute(args,exec) {
        const response=await fetch(base+'/call',{method:'POST',headers,signal:exec.signal,
          body:JSON.stringify({name:tool.name,args})});
        const value=await response.json();
        if(!response.ok || !value.success) throw new Error(value.error || '课程工具未完成');
        const content=[];
        for(const item of value.contentItems || []) {
          if(item.type==='inputText') content.push({type:'text',text:item.text});
          else if(item.type==='inputImage') {
            const match=/^data:(image\/[a-z]+);base64,(.+)$/s.exec(item.imageUrl);
            if(!match) throw new Error('课程图片格式不正确');
            const attachment=await ctx.attachments.saveImage({data:Buffer.from(match[2],'base64'),mediaType:match[1]});
            content.push({type:'image',attachment});
          }
        }
        return {content};
      },
    }));
  }
}
