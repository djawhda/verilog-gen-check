`timescale 1ns/1ps
// 自检测试台：随机读写 + 写满/读空边界，逐周期对比队列模型。
module tb_sync_fifo;
    reg clk = 0; always #5 clk = ~clk;
    reg rst = 1, wr_en = 0, rd_en = 0;
    reg [7:0] din = 8'bx;
    // 输入先是 x，1 ns 后再给初值：这样 0 时刻之后一定有一次输入变化，always @* 写的组合逻辑会被触发。
    // （SystemVerilog 里声明时的初值不产生事件；如果第一组激励恰好等于初值，always @* 一次都不执行，输出一直是 x。）
    initial #1 begin din = 0; end
    wire [7:0] dout; wire full, empty; wire [4:0] count;
    sync_fifo #(.W(8), .DEPTH_LOG2(4)) dut(.clk(clk), .rst(rst), .wr_en(wr_en), .din(din), .rd_en(rd_en),
        .dout(dout), .full(full), .empty(empty), .count(count));
    reg [7:0] q [0:15];
    integer head = 0, tail = 0, cnt = 0, errors = 0, k, phase, reads = 0, writes = 0;
    reg [7:0] exp_dout = 0;
    reg ok_w, ok_r;

    task automatic step(input w, input r, input [7:0] d);
        begin
            @(negedge clk);
            wr_en = w; rd_en = r; din = d;
            #1;
            if (count !== cnt || empty !== (cnt == 0) || full !== (cnt == 16)) begin
                errors = errors + 1;
                if (errors < 10) $display("TB_FAIL flags: expected count=%0d empty=%0d full=%0d got %0d %0d %0d", cnt, cnt == 0, cnt == 16, count, empty, full);
            end
            ok_w = w && (cnt < 16); ok_r = r && (cnt > 0);
            @(posedge clk);
            if (ok_r) begin exp_dout = q[head]; head = (head + 1) % 16; cnt = cnt - 1; reads = reads + 1; end
            if (ok_w) begin q[tail] = d; tail = (tail + 1) % 16; cnt = cnt + 1; writes = writes + 1; end
            #1;
            if (dout !== exp_dout) begin
                errors = errors + 1;
                if (errors < 10) $display("TB_FAIL dout: expected %h got %h (read=%0d write=%0d count=%0d)", exp_dout, dout, ok_r, ok_w, cnt);
            end
        end
    endtask

    initial begin
        repeat (2) @(posedge clk); @(negedge clk); rst = 0;
        for (k = 0; k < 20; k = k + 1) step(1, 0, k);            // 写满并继续写
        step(1, 1, 8'hAA);                                       // 满时同时读写
        for (k = 0; k < 20; k = k + 1) step(0, 1, 0);            // 读空并继续读
        step(1, 1, 8'h55);                                       // 空时同时读写
        for (phase = 0; phase < 3; phase = phase + 1)
            for (k = 0; k < 1500; k = k + 1)
                step(($random & 3) > phase, ($random & 3) >= 2 - phase, $random);
        @(negedge clk); rst = 1; @(negedge clk); rst = 0; #1;
        if (count !== 0 || !empty || dout !== 0) begin errors = errors + 1; $display("TB_FAIL reset"); end
        if (errors == 0) $display("TB_PASS sync_fifo: %0d writes, %0d reads", writes, reads);
        else $display("TB_FAIL sync_fifo: %0d errors", errors);
        $finish;
    end
endmodule
