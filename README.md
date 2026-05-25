<div align="center">
  <h1>fir-proxy</h1>
  <p><strong>一个高可用的 HTTP/SOCKS5 代理池，具有强大的图形化界面和多种代理获取方式。</strong></p>
    <p><strong>本项目基于 https://github.com/11firefly11/fir-proxy 进行开发和优化。</strong></p>
  <p>


  </p>
</div>

<hr/><h3 align="center">最好是导入可用代理哦,里面都是稳定的,且速度比较快的代理</h3>

<h2 align="center"> ✨ 项目特点 </h2>

<table border="0" cellpadding="10" cellspacing="0" width="100%">
  <tr valign="top">
    <td width="50%">
      <ul>
        <li><b>图形化界面</b>：基于 ttkbootstrap 的现代化图形界面，操作直观。</li>
        <li><b>多种代理源</b>：支持从在线API、网页抓取、本地文件等多种方式获取。</li>
        <li><b>高质量验证</b>：通过延迟、速度和国际连通性测试，确保代理真实可用。</li>
      </ul>
    </td>
    <td width="50%">
      <ul>
        <li><b>双协议服务</b>：一键启动本地 HTTP (127.0.0.1:1801) 和 SOCKS5 (127.0.0.1:1800) 服务。</li>
        <li><b>智能轮换与筛选</b>：支持按区域、质量筛选代理，并可按设定时间自动轮换IP。</li>
        <li><b>智能验证域名可达</b>：可设定指定目标域名和请求间隔，智能验证是否已被WAF拦截并自动轮换IP。</li>
        <li><b>丰富的管理功能</b>：支持导出、复制、删除和全部重新测试等多种管理操作。</li>
      </ul>
    </td>
  </tr>
</table>



<hr/>

<h2 align="center"> 📸 界面截图 </h2>
<img src=https://github.com/RuanLang0777/fir-proxy/blob/master/img/%E4%BB%A3%E7%90%86%E6%B1%A0.png>
<img src=https://github.com/RuanLang0777/fir-proxy/blob/master/fir-proxy%20-%201.2/img/fofa%E6%94%B6%E9%9B%86.png>
<img src=https://github.com/RuanLang0777/fir-proxy/blob/master/fir-proxy%20-%201.2/img/IP%E8%BD%AE%E6%8D%A2.png>
<p align="center">

</p>

<hr/>

<h2 align="center"> 🚀 快速开始 </h2>

<div align="center">
  <p><strong>环境要求:</strong> Python 3.10 或更高版本。</p>
</div>

<ol>
  <li>
    <strong>克隆或下载项目</strong>
<pre><code>git clone https://github.com/RuanLang0777/fir-proxy.git
cd fir-proxy</code></pre>
  </li>
  <li>
    <strong>安装依赖</strong>
<pre><code>pip install -r requirements.txt</code></pre>
  </li>
  <li>
    <strong>运行主程序</strong>
<pre><code>python main.py</code></pre>
  </li>
</ol>

<hr/>

<h2 align="center"> 📖 使用指南 </h2>

<h3 align="left">图形化界面 (main.py)</h3>

<ul>
  <li><b>获取代理</b>：
    <ul>
      <li><b>在线获取</b>：点击 <b>[获取在线代理]</b> 或者右键点击使用代理按钮，程序将自动从多个源抓取并验证。</li>
      <li><b>本地导入</b>：点击 <b>[导入代理]</b> 按钮，选择本地的 <code>.txt</code> 或 <code>.json</code> 文件。(建议选择导入可用代理里面的,里面的代理速度快且延迟也比较低)</li>
    </ul>
  </li>
  <br/>
  <li><b>使用代理</b>：
    <ul>
      <li>点击 <b>[启动服务]</b> 按钮，开启本地 <code>127.0.0.1:1801 (HTTP)</code> 和 <code>127.0.0.1:1800 (SOCKS5)</code> 端口。</li>
      <li>在需要代理的软件中配置上述地址即可。</li>
    </ul>
  </li>
  <br/>
  <li><b>IP 轮换</b>：
    <ul>
      <li><b>手动</b>：点击 <b>[轮换IP]</b> 立即切换。</li>
      <li><b>自动</b>：点击 <b>[自动]</b> 并设置秒数，程序将按时自动切换。</li>
      <li><b>自动</b>：点击 <b>[设置 -> IP轮换]</b> 并设置目标域名及请求间隔，程序将按时自动切换。</li>
    </ul>
  </li>
</ul>



<h3 align="left">独立命令行脚本 (hq.py / xdl.py)</h3>
<p>这两个脚本适合在服务器等无图形界面的环境下快速获取代理。</p>

<ul>
  <li><b>使用方法</b>：</li>
</ul>
<p><i># 运行智能模式脚本 (代理数量多,大约有30多w)</i></p>
<pre><code>python hq.py</code></pre>

<p><i># 运行常规模式脚本(推荐,有2000多个，实际可用ip不多但快速)</i></p>
<pre><code>python xdl.py</code></pre>

<ul>
  <li><b>生成文件</b>：脚本运行完毕后，会在当前目录下生成 <code>http.txt</code> 和 <code>git.txt</code> (SOCKS5代理) 文件。</li>
</ul>
