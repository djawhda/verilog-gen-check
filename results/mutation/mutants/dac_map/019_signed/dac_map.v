`timescale 1ns/1ps
// 标准答案：dac_map
module dac_map #(
    parameter [31:0] G = 32'sd26817,
    parameter signed [47:0] O = 48'sd536870912,
    parameter integer       S = 20
)(
    input  wire               clk,
    input  wire               rst,
    input  wire               in_valid,
    input  wire signed [15:0] x,
    output reg         [9:0]  code,
    output reg                sat,
    output reg                out_valid
);
    wire signed [47:0] x48 = $signed({{32{x[15]}}, x});   // 显式符号扩展
    wire signed [47:0] g48 = $signed({{16{G[31]}}, G});
    wire signed [47:0] acc = x48 * g48 + O;
    wire signed [47:0] y   = acc >>> S;
    wire               lo  = y < 48'sd0;
    wire               hi  = y > 48'sd1023;

    always @(posedge clk) begin
        if (rst) begin
            code      <= 10'd512;
            sat       <= 1'b0;
            out_valid <= 1'b0;
        end else begin
            out_valid <= in_valid;
            if (in_valid) begin
                code <= lo ? 10'd0 : (hi ? 10'd1023 : y[9:0]);
                sat  <= lo | hi;
            end
        end
    end
endmodule
