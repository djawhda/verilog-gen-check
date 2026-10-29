`timescale 1ns/1ps
// 自检测试台：CLKS_PER_BIT=6，逐周期检查 tx 和 busy；含背靠背发送和忙时 start。
module tb_uart_tx;
    localparam integer C = 6;
    reg clk = 0; always #5 clk = ~clk;
    reg rst = 1, start = 0; reg [7:0] data = 0;
    wire tx, busy;
    uart_tx #(.CLKS_PER_BIT(C)) dut(.clk(clk), .rst(rst), .start(start), .data(data), .tx(tx), .busy(busy));
    integer errors = 0, frames = 0, k, e, j;
    reg [9:0] frame;

    // 在第 0 个沿（start 被采样）之前调用；检查随后 10*C 个周期
    task automatic send(input [7:0] d, input integer extra_start);
        begin
            @(negedge clk); start = 1; data = d;
            @(posedge clk); #1;                         // 第 0 个沿之后
            start = 0; data = ~d;                       // 改掉 data，验证已锁存
            frame = {1'b1, d, 1'b0};
            for (e = 0; e < 10 * C; e = e + 1) begin
                if (tx !== frame[e / C] || busy !== 1'b1) begin
                    errors = errors + 1;
                    if (errors < 10) $display("TB_FAIL data=%h cycle %0d (bit %0d): expected tx=%b busy=1 got tx=%b busy=%b", d, e, e / C, frame[e / C], tx, busy);
                end
                if (extra_start && e == 3 * C) start = 1;   // 忙时 start 应被忽略
                if (extra_start && e == 3 * C + 2) start = 0;
                @(posedge clk); #1;
            end
            if (tx !== 1'b1 || busy !== 1'b0) begin
                errors = errors + 1;
                if (errors < 10) $display("TB_FAIL data=%h after frame: expected idle tx=1 busy=0 got tx=%b busy=%b", d, tx, busy);
            end
            frames = frames + 1;
        end
    endtask

    initial begin
        repeat (2) @(posedge clk); #1;
        if (tx !== 1'b1 || busy !== 1'b0) begin errors = errors + 1; $display("TB_FAIL reset: tx=%b busy=%b", tx, busy); end
        @(negedge clk); rst = 0;
        repeat (3) @(posedge clk); #1;
        if (tx !== 1'b1) begin errors = errors + 1; $display("TB_FAIL idle tx not 1"); end
        send(8'h55, 0); send(8'hA3, 1); send(8'h00, 0); send(8'hFF, 0);
        for (k = 0; k < 30; k = k + 1) begin
            send($random, k % 3 == 0);
            for (j = 0; j < (k % 4); j = j + 1) @(posedge clk);
        end
        // 背靠背：停止位结束的沿就送新的 start
        @(negedge clk); start = 1; data = 8'h3C;
        @(posedge clk); #1; start = 0;
        repeat (10 * C - 1) @(posedge clk);
        @(negedge clk); start = 1; data = 8'hC3;
        @(posedge clk); #1; start = 0;
        if (tx !== 1'b0 || busy !== 1'b1) begin errors = errors + 1; $display("TB_FAIL back-to-back start not accepted: tx=%b busy=%b", tx, busy); end
        repeat (12 * C) @(posedge clk);
        if (errors == 0) $display("TB_PASS uart_tx: %0d frames, cycle-exact", frames);
        else $display("TB_FAIL uart_tx: %0d errors", errors);
        $finish;
    end
endmodule
