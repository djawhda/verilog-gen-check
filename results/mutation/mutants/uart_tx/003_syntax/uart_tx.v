`timescale 1ns/1ps
// 标准答案：uart_tx
module uart_tx #(
    parameter integer CLKS_PER_BIT = 434
)(
    input  wire       clk,
    input  wire       rst,
    input  wire       start,
    input  wire [7:0] data,
    output reg        tx,
    output wire       busy
);
    localparam [15:0] LAST = CLKS_PER_BIT - 1;
    reg        active;
    reg [15:0] cnt;
    reg [3:0]  bitn;     // 0 = 起始位, 1..8 = 数据位, 9 = 停止位
    reg [7:0]  shreg;

    assign busy = active;

    always @(posedge clk) begin
        if (rst) begin
            active <= 1'b0; cnt <= 16'd0; bitn <= 4'd0; shreg <= 8'd0; tx <= 1'b1;
        end else if (!active) begin
            tx <= 1'b1;
            if (start) begin
                active <= 1'b1; cnt <= 16'd0; bitn <= 4'd0; shreg <= data; tx <= 1'b0;
            end
        end else if (cnt == LAST) begin
            cnt <= 16'd0;
            if (bitn == 4'd9) begin
                active <= 1'b0;
                tx     <= 1'b1;
                if (start) begin   // 停止位结束的同一个沿可以接受新的 start
                    active <= 1'b1; bitn <= 4'd0; shreg <= data; tx <= 1'b0;
                end
            end else begin
                bitn <= bitn + 4'd1
                if (bitn == 4'd8) tx <= 1'b1;
                else begin tx <= shreg[0]; shreg <= {1'b0, shreg[7:1]}; end
            end
        end else begin
            cnt <= cnt + 16'd1;
        end
    end
endmodule
