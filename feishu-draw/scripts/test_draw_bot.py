import json
from pathlib import Path
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch
import draw_bot as draw


SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 600"><rect x="20" y="20" width="960" height="560" fill="#fff"/><text x="100" y="100" font-size="30">流程</text></svg>'


class ParserTests(unittest.TestCase):
    def test_text_and_rich_post_same_message_images(self):
        self.assertEqual(draw.parse_draw('/draw 甲→乙'), ('甲→乙', []))
        self.assertEqual(draw.parse_draw('/draw\n甲→乙\n![Image](img_v3_abc)\n![Image](img_v3_abc)'), ('甲→乙', ['img_v3_abc']))
        self.assertEqual(draw.parse_draw('/draw 按图重绘\n[Image: img_v3_02175_2781d3cb-33e8-4b74-a563-9a7f16e380ag]'), ('按图重绘', ['img_v3_02175_2781d3cb-33e8-4b74-a563-9a7f16e380ag']))
        post = {'zh_cn': {'title': '架构图', 'content': [[{'tag':'text','text':'/draw 请重绘'}], [{'tag':'img','image_key':'img_v3_real'}]]}}
        self.assertEqual(draw.parse_draw(json.dumps(post)), ('请重绘', ['img_v3_real']))
        self.assertEqual(draw.parse_draw({'text':'/draw 描述'}), ('描述', []))

    def test_normal_chat_and_similar_commands_do_not_trigger(self):
        for value in ('/todo 画图', '/draws 流程', '请解释 /draw 怎么用', '普通聊天', '/draw:流程'):
            self.assertIsNone(draw.parse_draw(value))
        self.assertEqual(draw.parse_draw('/draw'), ('', []))

    def test_svg_must_keep_text_and_forbid_external_executable_content(self):
        self.assertEqual(draw.validate_svg(SVG), SVG)
        for bad in (
            SVG.replace('</svg>', '<script>alert(1)</script></svg>'),
            SVG.replace('<rect ', '<rect onclick="x()" '),
            SVG.replace('</svg>', '<image href="https://example.com/a.png"/></svg>'),
            '<!DOCTYPE svg [<!ENTITY e "boom">]>' + SVG,
            SVG.replace('1000 600', 'NaN 600'),
            SVG.replace('1000 600', '999999 600'),
            SVG.replace('流程','').replace('text','g'),
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(draw.DrawError):
                    draw.validate_svg(bad)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        cfg = dict(cli_path='/fake/lark-cli', profile='test', app_id='cli_test', owner_open_id='ou_test',
                   codex_path='/fake/codex', archive_document_id='doc_test', archive_document_url='https://example.feishu.cn/docx/doc_test',
                   state_dir=str(self.folder/'state'), timezone='Asia/Shanghai')
        self.config = self.folder/'config.json'
        self.config.write_text(json.dumps(cfg))
        self.app = draw.App(self.config)
        self.identity = patch.object(self.app, 'check_identity')
        self.identity.start()
        self.addCleanup(self.identity.stop)

    def event(self, value='/draw 甲→乙', **kwargs):
        return dict(message_id='om_test',sender_id='ou_test',sender_type='user',chat_type='p2p',message_type='text',content=value) | kwargs

    def new_job(self):
        with patch.object(self.app, 'emit'):
            return self.app.load(self.app.accept(self.event()))

    def test_owner_only_and_message_dedup(self):
        with patch.object(self.app, 'emit') as emit:
            for change in ({'sender_id':'ou_other'},{'chat_type':'group'},{'sender_type':'bot'},{'message_type':'image'}):
                self.assertIsNone(self.app.accept(self.event(**change)))
            self.assertIsNone(self.app.accept(self.event('普通聊天')))
            first = self.app.accept(self.event())
            self.assertEqual(self.app.accept(self.event()), first)
            emit.assert_called_once()
        with self.app.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0], 1)

    def test_state_cannot_be_reused_with_another_owner(self):
        cfg=json.loads(self.config.read_text());cfg['owner_open_id']='ou_other';self.config.write_text(json.dumps(cfg))
        with self.assertRaises(draw.DrawError):
            draw.App(self.config)

    def test_prompt_and_images_are_read_from_exact_original_message(self):
        job = self.new_job(); folder=self.app.jobs_dir/job['id'];folder.mkdir()
        actual=dict(messages=[dict(message_id='om_test',content='/draw 新描述\n![Image](img_v3_ref)')])
        def call(*args,**kwargs):
            if args[1] == '+messages-mget':
                return actual
            self.assertEqual(args[args.index('--message-id')+1], 'om_test')
            self.assertEqual(args[args.index('--file-key')+1], 'img_v3_ref')
            f=folder/'reference-1.png';f.write_bytes(b'image')
            return dict(saved_path=str(f))
        with patch.object(self.app,'call',side_effect=call):
            refs=self.app.references(job,folder)
        self.assertEqual(job['payload']['prompt'],'新描述')
        self.assertEqual(refs,[folder/'reference-1.png'])

    def test_crash_after_append_reconciles_without_duplicate_write(self):
        job=self.new_job();self.app.save(job,'appending')
        found=dict(board_token='board_real',block_id='block_real',url='https://example.feishu.cn/docx/doc_test#block_real')
        with patch.object(self.app,'find_archive',return_value=found),patch.object(self.app,'call') as call:
            self.app.archive(job,self.folder)
            call.assert_not_called()
        self.assertEqual(job['state'],'archived')
        self.assertEqual(job['payload']['board_token'],'board_real')

    def test_uncertain_append_is_never_repeated(self):
        job=self.new_job();self.app.save(job,'appending')
        with patch.object(self.app,'find_archive',return_value=None),patch.object(self.app,'call') as call:
            with self.assertRaises(draw.DrawError):
                self.app.archive(job,self.folder)
            call.assert_not_called()

    def test_new_date_has_date_only_and_no_svg_attachment_or_visible_id(self):
        job=self.new_job();job['event']['create_time']='1793861400000'
        job['payload'].update(title='绘图标题',references=[])
        folder=self.app.jobs_dir/job['id'];folder.mkdir()
        found=dict(board_token='new_board',block_id='new_block',url='https://example.feishu.cn/docx/doc_test#new_block')
        response={'document':{'new_blocks':[{'block_type':'whiteboard','block_token':'new_board'}]}}
        with patch.object(self.app,'date_section',return_value=(None,[])),patch.object(self.app,'find_archive',side_effect=[None,found]),patch.object(self.app,'finalize_archive'),patch.object(self.app,'call',return_value=response) as call:
            self.app.archive(job,folder)
        source=(folder/'archive.xml').read_text()
        self.assertIn('<h1>2026-11-05</h1>',source)
        self.assertNotIn('<source',source)
        self.assertNotIn('DRAW-',source)
        self.assertIn('<h2>绘图标题</h2>',source)
        self.assertLess(source.index('<whiteboard'),source.index('<h3>提示词与参考图</h3>'))
        args=call.call_args.args
        self.assertEqual(args[args.index('--command')+1],'append')
        self.assertEqual(job['payload']['written_board_token'],'new_board')

    def test_same_date_reuses_heading_with_one_blank_separator(self):
        job=self.new_job();job['event']['create_time']='1793861400000';job['payload'].update(title='测试',references=[])
        folder=self.app.jobs_dir/job['id'];folder.mkdir()
        heading=ET.fromstring('<h1 id="date">2026-11-05</h1>')
        board=ET.fromstring('<whiteboard id="previous" token="old_board"/>')
        found=dict(board_token='new_board',block_id='new_block',url='https://example.feishu.cn/docx/doc_test#new_block')
        with patch.object(self.app,'date_section',return_value=(heading,[heading,board])),patch.object(self.app,'find_archive',side_effect=[None,found]),patch.object(self.app,'finalize_archive'),patch.object(self.app,'call',return_value={}) as call:
            self.app.archive(job,folder)
        source=(folder/'archive.xml').read_text()
        self.assertTrue(source.startswith('<h2><br/>测试</h2>\n'))
        self.assertNotIn('<h1>',source)
        args=call.call_args.args
        self.assertEqual(args[args.index('--command')+1],'block_insert_after')
        self.assertEqual(args[args.index('--block-id')+1],'previous')
        self.assertEqual(job['payload']['before_boards'],['old_board'])

    def test_all_three_bot_replies_and_original_request_resolve_same_drawing(self):
        job=self.new_job()
        with self.app.db() as db:
            for stage in ('ack','preview','result'):
                db.execute('INSERT INTO receipts VALUES(?,?,?,?,?)',(job['id'],stage,'sent',time.time(),'om_'+stage))
        for stage in ('ack','preview','result'):
            self.assertEqual(self.app.reply_target('om_'+stage),job['id'])
        self.assertEqual(self.app.reply_target('om_test'),job['id'])
        self.assertIsNone(self.app.reply_target('om_unrelated'))

    def test_plain_reply_edits_but_unrelated_chat_or_other_command_does_not(self):
        job=self.new_job()
        with self.app.db() as db:db.execute('INSERT INTO receipts VALUES(?,?,?,?,?)',(job['id'],'result','sent',time.time(),'om_result'))
        with patch.object(self.app,'emit'):
            edit=self.app.accept(self.event('把第二步改成审核',message_id='om_edit',reply_to='om_result'))
            self.assertEqual(self.app.load(edit)['payload']['target_job_id'],job['id'])
            self.assertIsNone(self.app.accept(self.event('/todo 写周报',message_id='om_todo',reply_to='om_result')))
            self.assertIsNone(self.app.accept(self.event('普通聊天',message_id='om_normal')))

    def test_link_edit_requires_unique_target_and_preserves_instruction(self):
        url='https://example.feishu.cn/docx/doctest#b'
        self.assertEqual(draw.edit_link('修改 '+url+'：将标题改短'),(url,'将标题改短'))
        data={'document':{'document_id':'doc_test','content':'<h2 id="a">A</h2><whiteboard id="b" token="board_a"/><whiteboard id="c" token="board_b"/>'}}
        with patch.object(self.app,'call',return_value=data):
            self.assertEqual(self.app.locate_board(url)['board_token'],'board_a')
            with self.assertRaises(draw.DrawError):self.app.locate_board(url.split('#')[0])
            with self.assertRaises(draw.DrawError):self.app.locate_board('https://foreign.example/docx/doc_test#b')

    def test_fold_api_sets_only_folded_and_verifies_readback(self):
        result={'block':{'heading3':{'style':{'folded':True}}}}
        with patch.object(self.app,'call',return_value=result) as call:
            self.app.fold_details('doc_test','h3')
        args=call.call_args_list[0].args
        body=json.loads(args[args.index('--data')+1])
        self.assertEqual(body,{'update_text_style':{'style':{'folded':True},'fields':[3]}})

    def test_modification_prompt_appends_blank_line_and_does_not_repeat_on_retry(self):
        job=self.new_job();job['payload'].update(target_doc_id='doc_test',block_id='b',edit_instruction='标题改短',references=[])
        heading=ET.fromstring('<h2 id="h2">标题</h2>');details=ET.fromstring('<h3 id="h3">提示词与参考图</h3>')
        before=ET.fromstring('<pre id="p"><code>初次描述<br/>第二行</code></pre>')
        after=ET.fromstring('<pre id="new"><code>初次描述<br/>第二行<br/><br/>修改：标题改短</code></pre>')
        with patch.object(self.app,'drawing_details',side_effect=[(heading,details,before),(heading,details,after)]),patch.object(self.app,'fold_details'),patch.object(self.app,'call') as call:
            self.app.log_edit(job)
            self.assertEqual(call.call_count,1)
        self.assertEqual(job['payload']['history_after'],'初次描述\n第二行\n\n修改：标题改短')
        with patch.object(self.app,'drawing_details',return_value=(heading,details,after)),patch.object(self.app,'fold_details'),patch.object(self.app,'call') as call:
            self.app.log_edit(job);call.assert_not_called()

    def test_edit_does_not_overwrite_if_board_changed_during_generation(self):
        job=self.new_job();folder=self.app.jobs_dir/job['id'];folder.mkdir()
        job['payload'].update(board_token='board',edit_base_fingerprint='old')
        def export(*args,**kwargs):
            (folder/'edit-current-nodes.json').write_text(json.dumps({'nodes':[{'id':'new','text':{'text':'用户刚改了'}}]}));return {}
        with patch.object(self.app,'call',side_effect=export) as call:
            with self.assertRaisesRegex(draw.DrawError,'生成期间'):
                self.app.apply_edit(job,folder)
            self.assertFalse(any('+update' in c.args for c in call.call_args_list))

    def test_daily_reconciliation_identifies_returned_token_among_same_day_boards(self):
        job=self.new_job();job['payload'].update(archive_layout='daily',archive_date='2026-11-05',before_boards=['old'],written_board_token='new')
        heading=ET.fromstring('<h1 id="date">2026-11-05</h1>')
        boards=[ET.fromstring('<whiteboard id="a" token="old"/>'),ET.fromstring('<whiteboard id="b" token="new"/>')]
        with patch.object(self.app,'date_section',return_value=(heading,boards)):
            found=self.app.find_archive(job)
        self.assertEqual(found['block_id'],'b')

    def test_ambiguous_daily_reconciliation_requires_matching_diagram_text(self):
        job=self.new_job();job['payload'].update(archive_layout='daily',archive_date='2026-11-05',before_boards=[])
        folder=self.app.jobs_dir/job['id'];folder.mkdir();(folder/'diagram.svg').write_text(SVG)
        heading=ET.fromstring('<h1 id="date">2026-11-05</h1>')
        boards=[ET.fromstring('<whiteboard id="b" token="new"/>')]
        def export(*args,**kwargs):
            (folder/'reconcile-nodes.json').write_text(json.dumps({'nodes':[{'text':{'text':'流程'}}]}))
            return {}
        with patch.object(self.app,'date_section',return_value=(heading,boards)),patch.object(self.app,'call',side_effect=export):
            self.assertEqual(self.app.find_archive(job)['board_token'],'new')
        (folder/'diagram.svg').write_text(SVG.replace('流程','另一图'))
        with patch.object(self.app,'date_section',return_value=(heading,boards)),patch.object(self.app,'call',side_effect=export):
            with self.assertRaises(draw.DrawError):
                self.app.find_archive(job)

    def test_delivery_receipts_resume_without_resending_successful_preview(self):
        job=self.new_job()
        with patch.object(self.app,'call',return_value={'message_id':'om_reply'}) as call:
            self.app.emit(job,'preview',image=self.folder/'reply-preview.png')
            self.app.emit(job,'preview',image=self.folder/'reply-preview.png')
            self.assertEqual(call.call_count,1)
            self.assertIn('--image',call.call_args.args)
        with self.app.db() as db:
            db.execute('INSERT INTO receipts VALUES(?,?,?,?,?)',(job['id'],'result','pending',time.time()-4000,None))
        with patch.object(self.app,'call') as call:
            with self.assertRaises(draw.DrawError):
                self.app.emit(job,'result',text='完成')
            call.assert_not_called()

    def test_model_receives_reference_image_and_cannot_execute_shell(self):
        output=self.folder/'result.json'
        output.write_text(json.dumps(dict(title='测试',svg=SVG,summary='',notes=[])))
        response=type('Result',(),dict(returncode=0))()
        with patch.object(draw.subprocess,'run',return_value=response) as run:
            self.app.model('绘图需求',[self.folder/'reference.png'],self.folder/'schema.json',output)
        args=run.call_args.args[0]
        self.assertIn('read-only',args)
        self.assertIn('shell_tool',args)
        self.assertIn('--ignore-user-config',args)
        self.assertEqual(args[args.index('--image')+1],str(self.folder/'reference.png'))
        self.assertFalse(run.call_args.kwargs.get('shell',False))


if __name__=='__main__':
    unittest.main()
